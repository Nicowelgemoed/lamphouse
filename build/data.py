"""Load Kodak stock data (digitized by spektrafilm, CC BY-SA 4.0) and light sources
onto a common spectral grid. All spectra are returned as numpy arrays on `wl`."""
import json
import numpy as np
import colour
import config

SPK = config.SPEKTRAFILM_DATA
NEGATIVES = ['kodak_vision3_500t', 'kodak_vision3_250d', 'kodak_vision3_200t', 'kodak_vision3_50d']
PRINTS = ['kodak_2383', 'kodak_2393']


def grid(step=5.0, lo=380.0, hi=780.0):
    return np.arange(lo, hi + 1e-6, step)


def _fill(wl, y):
    """Fill NaNs by linear interpolation, holding the nearest valid value at the ends."""
    y = np.array(y, float)
    m = ~np.isnan(y)
    return np.interp(wl, wl[m], y[m])


def _resample(src_wl, y, wl):
    return np.interp(wl, src_wl, y)


def load_stock(name, wl):
    p = json.load(open(SPK + 'profiles/' + name + '.json'))
    d = p['data']
    swl = np.array(d['wavelengths'], float)
    out = {'name': p['info']['name'], 'info': p['info']}
    sens = np.array(d['log_sensitivity'], float)
    dyes = np.array(d['channel_density'], float)
    out['log_sens'] = np.stack([_resample(swl, _fill(swl, sens[:, c]), wl) for c in range(3)], 1)
    out['dyes'] = np.stack([_resample(swl, _fill(swl, dyes[:, c]), wl) for c in range(3)], 1)
    out['base'] = _resample(swl, _fill(swl, d['base_density']), wl)
    out['log_exposure'] = np.array(d['log_exposure'], float)
    curves = np.array(d['density_curves'], float)
    out['curves'] = np.stack([_fill(out['log_exposure'], curves[:, c]) for c in range(3)], 1)
    return out


def blackbody(T, wl):
    v = colour.colorimetry.blackbody_spectral_radiance(wl * 1e-9, T)
    return v / v.mean()


def kg3(wl):
    a = np.loadtxt(SPK + 'filters/heat_absorbing/schott/KG3.csv', delimiter=',')
    a = a[np.argsort(a[:, 0])]
    return np.clip(np.interp(wl, a[:, 0], a[:, 1], left=a[0, 1], right=0.0), 0, 1)


def illuminant(kind, wl):
    if kind == 'T':
        s = blackbody(3200.0, wl)
    elif kind in ('D55', 'D65'):
        sd = colour.SDS_ILLUMINANTS[kind]
        s = np.interp(wl, sd.wavelengths, sd.values)
    elif kind == 'K75P':  # Kinoton 75P xenon projector lamp
        sd = colour.SDS_LIGHT_SOURCES['Kinoton 75P']
        s = np.interp(wl, sd.wavelengths, sd.values)
    elif kind == 'TH-KG3':  # tungsten halogen printer lamp behind a KG3 heat filter
        s = blackbody(3200.0, wl) * kg3(wl)
    else:
        raise ValueError(kind)
    s = np.asarray(s, float)
    return s / s.mean()


def cmfs(wl):
    c = colour.MSDS_CMFS['CIE 1931 2 Degree Standard Observer'].copy().interpolate(colour.SpectralShape(360, 830, 1))
    idx = (wl - 360).astype(int)
    return c.values[idx]
