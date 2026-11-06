"""Synthetic linear-DWG test scene: exposure ramp, ColorChecker, hue/saturation sweep, skin
tones, and small bright practicals on a dark ground to show halation."""
import numpy as np, colour
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as m, data as fd


def make(w=1920, h=1080):
    img = np.full((h, w, 3), 0.18 * 2 ** -1.0)
    # 1) exposure ramp -8..+8 stops across the top band, and stepped patches below it
    x = np.linspace(-8, 8, w)
    img[0:110] = (0.18 * 2.0 ** x)[None, :, None]
    for i, s in enumerate(range(-7, 8)):
        x0 = int(i * w / 15)
        img[115:200, x0 + 4:int((i + 1) * w / 15) - 4] = 0.18 * 2.0 ** s
    # 2) ColorChecker (spectral, rendered under D65 -> DWG)
    wl = fd.grid(5); d65 = fd.illuminant('D65', wl); cmf = fd.cmfs(wl)
    cc = np.array([np.interp(wl, sd.wavelengths, sd.values) for sd in colour.SDS_COLOURCHECKERS['ColorChecker N Ohta'].values()])
    rgb = ((cc * d65) @ cmf / (d65 @ cmf)[1]) @ m.XYZ_TO_DWG.T
    pw, ph, x0, y0 = 110, 110, 40, 240
    for k in range(24):
        r, c = divmod(k, 6)
        img[y0 + r * (ph + 10): y0 + r * (ph + 10) + ph, x0 + c * (pw + 10): x0 + c * (pw + 10) + pw] = rgb[k]
    # 3) hue x saturation sweep in Rec.2020 (rows: saturation, cols: hue), mid exposure
    hx0, hy0, hw, hh = 800, 240, 1080, 480
    hue = np.linspace(0, 1, hw, endpoint=False)
    sat = np.linspace(1.0, 0.0, hh)
    H, S = np.meshgrid(hue, sat)
    hsv = np.stack([H, S, np.full_like(H, 1.0)], -1)
    rgb2020 = colour.HSV_to_RGB(hsv) ** 2.2 * 0.35
    xyz = colour.RGB_to_XYZ(rgb2020, 'ITU-R BT.2020')
    img[hy0:hy0 + hh, hx0:hx0 + hw] = xyz @ m.XYZ_TO_DWG.T
    # 4) dark band with practicals: tungsten bulbs, a neon, a specular sun glint
    img[760:1080] = 0.18 * 2 ** -5
    def disc(cx, cy, r, val):
        yy, xx = np.ogrid[:h, :w]
        img[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = val
    warm = np.array([1.0, 0.62, 0.32])          # ~2800K-ish practical in DWG terms
    for i, cx in enumerate([120, 300, 480]):
        disc(cx, 900, 6 + 6 * i, warm * 2 ** (4 + 2 * i) * 0.18)
    img[880:890, 620:1000] = np.array([0.9, 0.05, 0.25]) * 2 ** 6 * 0.18     # red-pink neon tube
    img[930:940, 620:1000] = np.array([0.05, 0.55, 1.0]) * 2 ** 6 * 0.18     # blue neon tube
    disc(1200, 900, 3, np.ones(3) * 2 ** 10 * 0.18)                            # specular glint
    # window edge: very bright area next to dark (classic halation edge)
    img[800:1040, 1500:1880] = 0.18 * 2 ** 7
    img[840:1000, 1560:1820] = 0.18 * 2 ** -5
    return img


if __name__ == '__main__':
    np.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scene_dwg.npy'), make().astype(np.float32))
    print('saved')
