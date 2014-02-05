#!/usr/bin/env python3
# encoding: utf-8

"""Random vibration theory motions."""

import numpy as np

from scipy.interpolate import interp1d

import pyrvt.peak_calculators as peak_calculators


def compute_stress_drop(magnitude):
    """Compute the stress drop using Atkinson and Boore (2011) model.

    Parameters
    ----------
    magnitude : float
        moment magnitude of the stress drop.

    Returns
    -------
    stress_drop : float
        stress drop in bars.
    """

    return 10 ** (3.45 - 0.2 * max(magnitude, 5.))


def compute_geometric_spreading(dist, coefs):
    """Compute the geometric spreading defined by piecewise linear model.

    Parameters
    ----------
    dist : float
        closest distance to the rupture surface [km]

    coefs : list
        list of (slope, limit) tuples that define the attenuation. For an
        inifinite distance use None. For example, [(1, None)] would provide for
        1/R geometric spreading to an inifinite distance.

    Returns
    -------
    geometric_spreading : float
        geometric spreading function, Z(R)
    """

    initial = 1
    gs = 1
    for slope, limit in coefs:
        # Compute the distance limited by the maximum distance of the slope.
        _dist = min(dist, limit) if limit else dist
        gs *= (initial / _dist) ** slope

        if _dist < dist:
            initial = _dist
        else:
            break

    return gs


class RvtMotion(object):
    def __init__(self, freq=None, fourier_amp=None, duration=None,
                 peak_calculator=peak_calculators.LiuPezeshk1999()):
        self.freq = freq
        self.fourier_amp = fourier_amp
        self.duration = duration
        self.peak_calculator = peak_calculator

    def compute_osc_resp(self, osc_freq, damping=0.05):
        """Compute the response of an oscillator with a specific frequency and
        damping.

        Parameters
        ----------
        osc_freq : numpy.array
            Natural frequency of the oscillator [Hz]
        damping : float (optional)
            Fractional damping of the oscillator.

        Returns
        -------
        psa : numpy.array
            peak psuedo spectral acceleration of the oscillator
        """

        def compute_spec_accel(fn):
            # Compute the transfer function
            h = np.abs(-fn ** 2. / (np.square(self.freq) - np.square(fn)
                                    - 2.j * damping * fn * self.freq))

            return self.compute_peak(h, osc_freq=fn, osc_damping=damping)

        return np.array([compute_spec_accel(f) for f in osc_freq])

    def compute_peak(self, transfer_func=None, osc_freq=None, osc_damping=None):
        """Compute the peak response.

        """
        if transfer_func is None:
            fourier_amp = self.fourier_amp
        else:
            fourier_amp = transfer_func * self.fourier_amp

        return self.peak_calculator(self.duration, self.freq, fourier_amp,
                                    osc_freq, osc_damping)


class SourceTheoryMotion(RvtMotion):
    """Single-corner source theory model."""
    def __init__(self, magnitude, distance, region, stress_drop=None):
        super(SourceTheoryMotion, self).__init__(None, None, None)
        """Compute the duration using the Atkinson and Boore (1995) model.

        Parameters
        ----------
        magnitude : float
            moment magnitude of the event

        distance : float
            distance in km

        stress_drop : float or None
            stress drop of the event in bar. If stress_drop is None, then it
            will be computed using the Atkinson and Boore (2011) model.

        shear_velocity : float
            shear-wave velocity of the crustal in km/sec

        Returns
        -------
        duration : float
            ground motion duration
        """

        self.magnitude = magnitude
        self.distance = distance
        self.region = region.lower()

        if self.region == 'wus':
            # Default parameters for the WUS from Campbell (2003)
            self.shear_velocity = 3.5
            self.path_atten_coeff = 180.
            self.path_atten_power = 0.45
            self.density = 2.8
            self.site_atten = 0.04

            self.geometric_spreading = [(-1, 40), (-0.5, None)]

            if stress_drop:
                self.stress_drop = stress_drop
            else:
                self.stress_drop = 100.

            # Crustal amplification from Campbell (2003) using the
            # log-frequency and the amplification based on a quarter-wave
            # length approximation
            self.site_amp = interp1d(
                np.log([0.01, 0.09, 0.16, 0.51, 0.84, 1.25, 2.26, 3.17, 6.05,
                        16.60, 61.20, 100.00]),
                [1.00, 1.10, 1.18, 1.42, 1.58, 1.74, 2.06, 2.25, 2.58, 3.13,
                 4.00, 4.40])
        elif self.region == 'ceus':
            # Default parameters for the CEUS from Campbell (2003)
            self.shear_velocity = 3.6
            self.density = 2.8
            self.path_atten_coeff = 680.
            self.path_atten_power = 0.36
            self.site_atten = 0.006

            self.geometric_spreading = [(-1, 70), (0, 130), (-0.5, None)]

            if stress_drop:
                self.stress_drop = stress_drop
            else:
                self.stress_drop = 150.

            # Crustal amplification from Campbell (2003) using the
            # log-frequency and the amplification based on a quarter-wave
            # length approximation
            self.site_amp = interp1d(
                np.log([0.01, 0.10, 0.20, 0.30, 0.50, 0.90, 1.25, 1.80, 3.00,
                        5.30, 8.00, 14.00, 30.00, 60.00, 100.00]),
                [1.00, 1.02, 1.03, 1.05, 1.07, 1.09, 1.11, 1.12, 1.13, 1.14,
                 1.15, 1.15, 1.15, 1.15, 1.15])

        else:
            raise NotImplementedError

        # Depth to rupture
        self.depth = 8.
        self.hypo_distance = np.sqrt(self.distance ** 2. + self.depth ** 2.)

        # Constants
        self.seismic_moment = 10. ** (1.5 * (self.magnitude + 10.7))
        self.corner_freq = (4.9e6 * self.shear_velocity
                            * (self.stress_drop
                               / self.seismic_moment) ** (1./3.))

    def compute_duration(self):
        # Source component
        duration_source = 1. / self.corner_freq

        # Path component
        if self.region == 'wus':
            duration_path = 0.05 * self.hypo_distance
        elif self.region == 'ceus':
            duration_path = 0.

            if 10 < self.hypo_distance:
                # 10 < R <= 70 km
                duration_path += 0.16 * (min(self.hypo_distance, 70) - 10.)

            if 70 < self.hypo_distance:
                # 70 < R <= 130 km
                duration_path += -0.03 * (min(self.hypo_distance, 130) - 70.)

            if 130 < self.hypo_distance:
                # 130 km < R
                duration_path += 0.04 * (self.hypo_distance - 130.)
        else:
            raise NotImplementedError

        return duration_source + duration_path

    def compute_fourier_amp(self, freq):
        self.freq = np.asarray(freq)
        self.duration = self.compute_duration()

        # Model component
        const = (0.55 * 2.) / (np.sqrt(2.) * 4. * np.pi * self.density
                               * self.shear_velocity ** 3.)
        source_comp = (const * self.seismic_moment
                       / (1. + (self.freq / self.corner_freq) ** 2.))

        # Path component
        path_atten = self.path_atten_coeff * self.freq ** self.path_atten_power
        geo_atten = compute_geometric_spreading(self.hypo_distance,
                                                self.geometric_spreading)

        path_comp = geo_atten * np.exp(
            (-np.pi * self.freq * self.hypo_distance)
            / (path_atten * self.shear_velocity))

        # Site component
        site_dim = np.exp(-np.pi * self.site_atten * self.freq)
        site_comp = self.site_amp(np.log(self.freq)) * site_dim

        # Conversion factor to convert from dyne-cm into gravity-sec
        conv = 1.e-20 / 981.
        # Combine the three components and convert from displacement to
        # acceleleration
        self.fourier_amp = (conv * (2. * np.pi * self.freq) ** 2.
                            * source_comp * path_comp * site_comp)


class CompatibleRvtMotion(RvtMotion):
    def __init__(self, osc_freq, osc_resp_target, duration=None, damping=0.05,
                 magnitude=None, distance=None, stress_drop=None, region=None,
                 window_len=None):
        """Compute a Fourier amplitude spectrum that is compatible with a
        target response spectrum."""
        super(CompatibleRvtMotion, self).__init__(None, None, None)

        osc_freq = np.asarray(osc_freq)
        osc_resp_target = np.asarray(osc_resp_target)

        # Order by increasing frequency
        ind = osc_freq.argsort()
        osc_freq = osc_freq[ind]
        osc_resp_target = osc_resp_target[ind]

        if duration:
            self.duration = duration
        else:
            stm = SourceTheoryMotion(magnitude, distance, region, stress_drop)
            self.duration = stm.compute_duration()

        # Compute initial value using Vanmarcke methodology. The response is
        # first computed at the lowest frequency and then subsequently comptued
        # at higher frequencies.

        peak_factor = 2.5
        fa_sqr_cur = None
        fa_sqr_prev = 0.
        total = 0.

        sdof_factor = np.pi / (4. * damping) - 1.

        fourier_amp = np.empty_like(osc_freq)

        for i, (_osc_freq, _osc_resp) in enumerate(
                zip(osc_freq, osc_resp_target)):
            duration_rms = self._compute_duration_rms(
                _osc_freq, damping=damping, method='boore_joyner')

            fa_sqr_cur = (
                ((duration_rms * _osc_resp ** 2) / (2 * peak_factor ** 2) -
                 total) / (_osc_freq * sdof_factor))

            if fa_sqr_cur < 0:
                fourier_amp[i] = fourier_amp[i-1]
                fa_sqr_cur = fourier_amp[i] ** 2
            else:
                fourier_amp[i] = np.sqrt(fa_sqr_cur)

            if i == 0:
                total = fa_sqr_cur * _osc_freq / 2.
            else:
                total += ((fa_sqr_cur - fa_sqr_prev)
                          / 2 * (_osc_freq - osc_freq[i-1]))

        # The frequency needs to be extended to account for the fact that the
        # osciallator transfer function has a width.
        self.freq = np.logspace(
            np.log10(osc_freq[0] / 2.),
            np.log10(2 * osc_freq[-1]), 512)
        #self.freq = np.r_[osc_freq[0] / 2., osc_freq, 2. * osc_freq[-1]]
        self.fourier_amp = np.empty_like(self.freq)

        # Indices of the first and last point with the range of the provided
        # response spectra
        indices = np.argwhere(
            (osc_freq[0] < self.freq) & (self.freq < osc_freq[-1]))
        first = indices[0, 0]
        # last is extend one past the usable range to allow use of first:last
        # notation
        last = indices[-1, 0] + 1

        log_freq = np.log(self.freq)
        log_osc_freq = np.log(osc_freq)

        self.fourier_amp[first:last] = np.exp(np.interp(
            log_freq[first:last], log_osc_freq, np.log(fourier_amp)))

        def extrapolate():
            # Extrapolate the first and last value of Fourier amplitude
            # spectrum.
            def _extrap(freq_i, freq, fourier_amp, max_slope=None):
                # Extrapolation is performed in log-space using the first and
                # last two points
                xi = np.log(freq_i)
                x = np.log(freq)
                y = np.log(fourier_amp)

                slope = (y[1] - y[0]) / (x[1] - x[0])

                if max_slope:
                    slope = min(slope, max_slope)

                return np.exp(slope * (xi - x[0]) + y[0])

            # Update the first point using the second and third points
            self.fourier_amp[0:first] = _extrap(
                self.freq[0:first],
                self.freq[first:first+2],
                self.fourier_amp[first:first+2], None)
            # Update the last point using the third- and second-to-last points
            self.fourier_amp[last:] = _extrap(
                self.freq[last:],
                self.freq[last-2:last],
                self.fourier_amp[last-2:last], None)

        extrapolate()

        # Apply a ratio correction between the computed at target response
        # spectra
        self.iterations = 0
        self.rmse = 1.

        max_iterations = 30
        tolerance = 5e-6

        osc_resp = self.compute_osc_resp(osc_freq, damping)

        if window_len:
            window = np.ones(window_len, 'd')
            window /= window.sum()

        while self.iterations < max_iterations and tolerance < self.rmse:
            # Correct the FAS by the ratio of the target to computed
            # osciallator response. The ratio is applied over the same
            # frequency range. The first and last points in the FAS are
            # determined through extrapolation.

            self.fourier_amp[first:last] *= np.exp(np.interp(
                log_freq[first:last], log_osc_freq,
                np.log((osc_resp_target / osc_resp))))

            extrapolate()

            # Apply a running average to smooth the signal
            if window_len:
                self.fourier_amp = np.convolve(
                    window, self.fourier_amp, 'same')

            # Compute the fit between the target and computed oscillator
            # response
            self.rmse = np.sqrt(np.mean(
                (osc_resp_target
                 - self.compute_osc_resp(osc_freq, damping)) ** 2))

            self.iterations += 1

            # Recompute the response spectrum
            osc_resp = self.compute_osc_resp(osc_freq, damping)
