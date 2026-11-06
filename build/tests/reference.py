"""Render test patches through spektrafilm (reference) and through my model, side by side."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, colour, warnings
warnings.filterwarnings('ignore')
import model as m, data as fd
from spektrafilm.runtime.api import init_params, simulate


def test_patches():
    wl = fd.grid(5)
    d65 = fd.illuminant('D65', wl); cmf = fd.cmfs(wl)
    cc = np.array([np.interp(wl, sd.wavelengths, sd.values) for sd in colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'].values()])
    xyz = (cc * d65) @ cmf / (d65 @ cmf)[1]
    cc_rgb = xyz @ m.XYZ_TO_DWG.T
    stops = np.array([-6, -4, -3, -2, -1, 0, 1, 2, 3, 4, 6])
    grey = np.repeat(0.18 * 2.0 ** stops[:, None], 3, 1)
    names = list(colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'].keys())
    return np.vstack([cc_rgb, grey]), names + ['grey%+d' % s for s in stops]


def spektra(rgb_dwg, film, prt='kodak_2383'):
    p = init_params(film, prt)
    p.debug.lut_mode = True
    p.camera.auto_exposure = False
    p.io.input_color_space = 'DaVinci Wide Gamut'
    p.io.input_cctf_decoding = False
    p.io.output_color_space = 'ITU-R BT.709'
    p.io.output_cctf_encoding = False
    img = rgb_dwg.reshape(1, -1, 3).astype(np.float64)
    out = simulate(img, p)
    return np.asarray(out).reshape(-1, 3)


def mine(rgb_dwg, film, prt='kodak_2383', **kw):
    ch = m.Chain(film, prt, fd.grid(5)); m.fit_camera(ch); m.balance_printer(ch)
    return ch.render(rgb_dwg, **kw) @ m.REC709_XYZ_TO_RGB.T


if __name__ == '__main__':
    film = sys.argv[1] if len(sys.argv) > 1 else 'kodak_vision3_500t'
    rgb, names = test_patches()
    a = spektra(rgb, film); b = mine(rgb, film)
    enc = lambda x: np.clip(x, 0, 1) ** (1 / 2.4)
    lab = lambda x: colour.XYZ_to_Lab(colour.RGB_to_XYZ(np.clip(x, 0, None), 'ITU-R BT.709'))
    # normalise exposure so both render mid grey identically before comparing colour
    k = b[29, 1] / a[29, 1]
    print('spektrafilm mid grey 709 code', enc(a[29]).round(3), ' mine', enc(b[29]).round(3), ' lum ratio', round(k, 3))
    La, Lb = lab(a * k), lab(b)
    print('%-16s %-22s %-22s %6s %6s' % ('patch', 'spektra 709 code', 'mine 709 code', 'dE00', 'dC'))
    for i, n in enumerate(names):
        dE = colour.delta_E(La[i], Lb[i], method='CIE 2000')
        dC = np.hypot(*Lb[i, 1:]) - np.hypot(*La[i, 1:])
        print('%-16s %-22s %-22s %6.2f %6.1f' % (n[:16], enc(a[i] * k).round(3), enc(b[i]).round(3), dE, dC))
