"""Bake the calibrated model into AnswerPrint.dctl and Lamphouse.dctl (constants + kernel templates)."""
import datetime
import numpy as np
import colour
import data as fd
import model as m
import config

WL = fd.grid(10.0, 380.0, 740.0)      # DCTL spectral sampling
NC = 64                               # samples per characteristic curve (Catmull-Rom in the DCTL)
CURVE_LO, CURVE_HI = -3.0, 4.0
HAL_TAPS = 96
DIR_UNIT = 0.1          # interlayer slider unit; calibrated default slider value 0.3
GRAIN_CELL_UM = 8.0
# grain per stock: density sigma at a 48um aperture (VISION3 ordering: 50D finest, 500T coarsest)
NEG_GRAIN = {'kodak_vision3_500t': 0.0055, 'kodak_vision3_250d': 0.0041,
             'kodak_vision3_200t': 0.0039, 'kodak_vision3_50d': 0.0025}
NEG_HALATION = {'kodak_vision3_500t': 0.045, 'kodak_vision3_250d': 0.04,
                'kodak_vision3_200t': 0.04, 'kodak_vision3_50d': 0.04}


def fmt(name, arr, per_line=16):
    a = np.asarray(arr, float).ravel()
    body = ',\n    '.join(', '.join(('%.6g' % v).replace('e+0', 'e').replace('e-0', 'e-') + ('' if 'e' in ('%.6g' % v) or '.' in ('%.6g' % v) else '.0') + 'f' for v in a[i:i + per_line]) for i in range(0, len(a), per_line))
    return '__CONSTANT__ float %s[%d] = {\n    %s\n};\n' % (name, len(a), body)


def halation_taps(n=HAL_TAPS, bounces=3, decay=0.5):
    """Importance-sample the halation kernel (sum of 2D Gaussians, bounce k has sigma*sqrt(k)) so
    every tap has equal weight. Radii in units of the first-bounce sigma."""
    r = np.linspace(0, 8, 4001)
    pdf = sum(decay ** (k - 1) * (r / k) * np.exp(-r * r / (2 * k)) for k in range(1, bounces + 1))
    cdf = np.cumsum(pdf); cdf /= cdf[-1]
    u = (np.arange(n) + 0.5) / n
    radii = np.interp(u, cdf, r)
    return radii, np.ones(n)


def resample_curve(stock):
    x = np.linspace(CURVE_LO, CURVE_HI, NC)
    return np.stack([np.interp(x, stock['log_exposure'], stock['curves'][:, c]) for c in range(3)])


def build(dir_default, out_path):
    negs, prints = fd.NEGATIVES, fd.PRINTS
    chains = {}
    for n in negs:
        for p in prints:
            ch = m.Chain(n, p, WL)
            m.fit_camera(ch)
            m.balance_printer(ch, dir_amount=dir_default)
            chains[n, p] = ch
    c0 = {n: chains[n, prints[0]] for n in negs}
    p0 = {p: chains[negs[0], p] for p in prints}

    xyz2out = np.vstack([
        colour.RGB_COLOURSPACES['ITU-R BT.709'].matrix_XYZ_to_RGB,
        colour.RGB_COLOURSPACES['P3-D65'].matrix_XYZ_to_RGB,
        m.XYZ_TO_DWG,
    ])
    radii, weights = halation_taps()
    parts = [
        '#define NW %d\n#define NC %d\n#define HAL_TAPS %d\n' % (len(WL), NC, HAL_TAPS),
        '#define CURVE_LO %.4ff\n#define CURVE_HI %.4ff\n' % (CURVE_LO, CURVE_HI),
        '#define HAL_DR %.5ff\n' % float(np.mean(np.diff(radii)) * 2.0),
        '#define BB_POINTS_COMP 3.2f\n',
        '#define EXPOSURE_FLOOR %.5ff\n' % m.EXPOSURE_FLOOR,
        '#define DIR_UNIT %.5ff\n#define BB_SILVER %.4ff\n#define GRAIN_CELL_UM %.3ff\n\n' % (DIR_UNIT, m.BB_SILVER, GRAIN_CELL_UM),
                fmt('XYZ2OUT', xyz2out),
        fmt('HAL_R', radii), fmt('HAL_W', weights),
        fmt('NEG_CAM', np.stack([c0[n].cam for n in negs])),
        fmt('NEG_CURVE', np.stack([resample_curve(c0[n].neg) for n in negs])),
        fmt('NEG_GAMMA', np.stack([c0[n].neg_gamma for n in negs])),
        fmt('NEG_DYE', np.stack([c0[n].neg['dyes'].T for n in negs])),
        fmt('NEG_BASE', np.stack([c0[n].neg['base'] for n in negs])),
        fmt('NEG_GRAIN', [NEG_GRAIN[n] for n in negs]),
        fmt('NEG_HALATION', [NEG_HALATION[n] for n in negs]),
        fmt('PRT_W', np.stack([p0[p].W.reshape(9, -1) for p in prints])),   # (band, layer) rows
        fmt('PRT_DYE', np.stack([p0[p].prt['dyes'].T for p in prints])),
        fmt('PRT_BASE', np.stack([p0[p].prt['base'] for p in prints])),
        fmt('PRT_PROJ', np.stack([p0[p].proj_xyz.T for p in prints])),
        fmt('PRT_CURVE', np.stack([resample_curve(p0[p].prt) for p in prints])),
        fmt('PAIR_GAIN', np.stack([[chains[n, p].log_gain for p in prints] for n in negs])),
        fmt('PAIR_PIVOT', np.stack([[chains[n, p].pivot for p in prints] for n in negs])),
    ]
    tpl = open(config.TEMPLATES + '/answerprint.dctl').read()
    stamp = '%s, %s, %d nm x %d samples' % ('v' + config.VERSION, datetime.date.today().isoformat(), int(WL[1] - WL[0]), len(WL))
    src = tpl.replace('// @@CONSTANTS@@', ''.join(parts)).replace('@@BUILD@@', stamp).replace('@@AUTHOR@@', config.AUTHOR).replace('@@URL@@', config.PROJECT_URL)
    if out_path:
        open(out_path, 'w').write(src)
    global LAST_CONSTANTS, LAST_STAMP
    LAST_CONSTANTS, LAST_STAMP = ''.join(parts), stamp   # reused by build_lamphouse()
    n_floats = sum(int(s.split('[')[1].split(']')[0]) for s in parts if s.startswith('__CONSTANT__'))
    return chains, n_floats


TS_CONTRAST = 1.4   # Lamphouse reference tonescale exponent (only shapes how other displays extend the look)

# Lamphouse input spaces: (colour-science gamut name) in UI order; transfer functions are in the template
LH_INPUTS = ['DaVinci Wide Gamut', 'ACEScg', 'ARRI Wide Gamut 3', 'ARRI Wide Gamut 4',
             'S-Gamut3.Cine', 'REDWideGamutRGB', 'V-Gamut', 'DaVinci Wide Gamut']


def lamphouse_constants():
    dwg = colour.RGB_COLOURSPACES['DaVinci Wide Gamut']
    to_dwg = [colour.matrix_RGB_to_RGB(colour.RGB_COLOURSPACES[n], dwg, chromatic_adaptation_transform='Bradford')
              for n in LH_INPUTS]
    rec2020 = colour.RGB_COLOURSPACES['ITU-R BT.2020']
    from2020 = [colour.matrix_RGB_to_RGB(rec2020, colour.RGB_COLOURSPACES[n]) for n in ('ITU-R BT.709', 'P3-D65', 'ITU-R BT.2020', 'DaVinci Wide Gamut')]
    p3_to_2020 = colour.matrix_RGB_to_RGB(colour.RGB_COLOURSPACES['P3-D65'], rec2020)
    # creative white: Rec.2020-domain Bradford adaptation D65 -> white, plus per-gamut (709, P3) scale so white peaks at 1
    obs = colour.CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer']
    xyz_to_2020, to_xyz = rec2020.matrix_XYZ_to_RGB, rec2020.matrix_RGB_to_XYZ
    cw_m, cw_k = [], []
    for w in ('D65', 'D60', 'D55', 'D50'):
        cat = colour.adaptation.matrix_chromatic_adaptation_VonKries(
            colour.xy_to_XYZ(obs['D65']), colour.xy_to_XYZ(obs[w]), transform='Bradford')
        M = xyz_to_2020 @ cat @ to_xyz
        cw_m.append(M)
        white = M @ np.ones(3)
        cw_k.extend([1.0 / (from2020[g] @ white).max() for g in (0, 1)])
    a = (2.0 ** 18 - 16.0) / 117.45
    b = (1023.0 - 95.0) / 1023.0
    c = 95.0 / 1023.0
    s_ = (7.0 * np.log(2.0) * 2.0 ** (7.0 - 14.0 * c / b)) / (a * b)
    t_ = (2.0 ** (14.0 * (-c / b) + 6.0) - 64.0) / a
    return ''.join([
        '#define TS_CONTRAST %.4ff\n' % TS_CONTRAST,
        '#define LOGC4_A %.9gf\n#define LOGC4_B %.9gf\n#define LOGC4_C %.9gf\n#define LOGC4_S %.9gf\n#define LOGC4_T %.9gf\n' % (a, b, c, s_, t_),
        fmt('IN_TO_DWG', np.stack(to_dwg)),
        fmt('XYZ_TO_2020', rec2020.matrix_XYZ_to_RGB),
        fmt('M2020_TO', np.stack(from2020)),
        fmt('P3_TO_2020', p3_to_2020),
        fmt('CW_M', np.stack(cw_m)),
        fmt('CW_K', np.array(cw_k)),
    ])


def build_lamphouse(out_path):
    """Requires build() to have run first in this process (it produces the shared film constants)."""
    tpl = open(config.TEMPLATES + '/lamphouse.dctl').read()
    src = tpl.replace('// @@CONSTANTS@@', LAST_CONSTANTS + lamphouse_constants()).replace('@@BUILD@@', 'Lamphouse ' + LAST_STAMP)
    src = src.replace('@@AUTHOR@@', config.AUTHOR).replace('@@URL@@', config.PROJECT_URL)
    src = src.replace('// Build: Answer Print', '// Build:')
    open(out_path, 'w').write(src)
    return src


if __name__ == '__main__':
    import sys
    chains, nf = build(float(sys.argv[1]) if len(sys.argv) > 1 else 0.03, config.OUT_STANDALONE)
    build_lamphouse(config.OUT_LAMPHOUSE)
    print('wrote', config.OUT_STANDALONE, 'and', config.OUT_LAMPHOUSE)
