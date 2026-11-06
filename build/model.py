"""Reference implementation of the film chain. Every step here is mirrored 1:1 in the DCTL,
so this file is both the calibration tool and the ground truth for testing the DCTL math.

Chain: DaVinci Intermediate -> linear DWG -> [halation] -> negative layer exposures (3x3)
       -> log exposure -> interlayer (DIR) effect -> negative densities (Kodak curves) [+grain]
       -> negative spectral transmittance -> additive printer (R/G/B bands, printer points)
       -> print layer exposures -> print densities (Kodak curves) [+bleach bypass silver]
       -> print spectral transmittance -> projector lamp -> CIE XYZ -> CAT to D65 -> display
"""
import numpy as np
import colour
import data as fd

POINT = 0.025          # one printer point in log exposure
NOMINAL_POINTS = 25.0
LAD_PRINT_DENSITY = 1.0  # Kodak LAD aim: 18% grey prints to ~1.0 visual density

# ---------- colour spaces ----------
DWG = colour.RGB_COLOURSPACES['DaVinci Wide Gamut']
DWG_TO_XYZ = DWG.matrix_RGB_to_XYZ
XYZ_TO_DWG = DWG.matrix_XYZ_to_RGB
REC709_XYZ_TO_RGB = colour.RGB_COLOURSPACES['ITU-R BT.709'].matrix_XYZ_to_RGB
D65_xy = np.array([0.3127, 0.3290])


def di_decode(x):
    x = np.asarray(x, float)
    return np.where(x <= 0.02740668, x / 10.44426855, np.exp2(x / 0.07329248 - 7.0) - 0.0075)


def di_encode(y):
    y = np.asarray(y, float)
    return np.where(y <= 0.00262409, y * 10.44426855, (np.log2(np.maximum(y + 0.0075, 1e-10)) + 7.0) * 0.07329248)


def bradford(src_xy, dst_xy=D65_xy):
    return colour.adaptation.matrix_chromatic_adaptation_VonKries(
        colour.xy_to_XYZ(src_xy), colour.xy_to_XYZ(dst_xy), transform='Bradford')


# ---------- spectral helpers ----------
def printer_bands(wl, edge_bg=492.0, edge_gr=588.0, width=6.0):
    """Dichroic separation of an additive printer into blue, green, red light bands."""
    s = lambda x: 1.0 / (1.0 + np.exp(-x / width))
    blue = 1.0 - s(wl - edge_bg)
    red = s(wl - edge_gr)
    green = 1.0 - blue - red
    return np.stack([red, green, blue], 1)   # order R, G, B to match layers


class Chain:
    """Holds all precomputed spectral data for one negative + print pairing."""

    def __init__(self, neg_name, print_name, wl):
        self.wl = wl
        self.neg_name = neg_name
        self.print_name = print_name
        self.dw = wl[1] - wl[0]
        self.neg = fd.load_stock(neg_name, wl)
        self.prt = fd.load_stock(print_name, wl)
        ref = self.neg['info']['reference_illuminant']
        self.ref_ill = fd.illuminant('T' if ref == 'T' else 'D55', wl)
        self.lamp = fd.illuminant('TH-KG3', wl)
        self.proj = fd.illuminant('K75P', wl)
        self.cmf = fd.cmfs(wl)
        self.neg_sens = 10.0 ** self.neg['log_sens']
        self.prt_sens = 10.0 ** self.prt['log_sens']
        # printer: W[b, k, wl] = lamp * band_b * print sensitivity_k
        bands = printer_bands(wl)
        self.W = np.einsum('l,lb,lk->bkl', self.lamp, bands, self.prt_sens) * self.dw
        # projection to XYZ, normalised so the clear print (base only) has Y = 1, adapted to D65
        P = self.proj[:, None] * self.cmf * self.dw
        white = (10.0 ** -self.prt['base']) @ P
        P = P / white[1]
        cat = bradford(colour.XYZ_to_xy(white))
        self.proj_xyz = P @ cat.T                     # (wl, 3) -> D65-adapted XYZ
        self.cam = None
        self.log_gain = np.zeros(3)
        self.neg_gamma = self._mid_gamma(self.neg)

    @staticmethod
    def _mid_gamma(stock, lo=-0.5, hi=0.5):
        le = stock['log_exposure']
        return np.array([(np.interp(hi, le, stock['curves'][:, c]) - np.interp(lo, le, stock['curves'][:, c])) / (hi - lo)
                         for c in range(3)])

    # ----- stage: scene -> negative log exposure -----
    def exposure(self, lin_dwg):
        return soft_floor(rootpoly(lin_dwg) @ self.cam.T)

    # ----- stage: develop negative -----
    def develop_negative(self, E, dir_amount=0.0, dir_w=None, push=0.0):
        le = self.neg['log_exposure']
        logE = np.log10(np.maximum(E, 1e-6))
        gam = 1.0 + 0.12 * push                 # development push/pull scales contrast about mid-grey
        speed = 0.10 * push                     # and shifts effective speed slightly
        curve = lambda x, c: np.interp((x + speed) * gam, le, self.neg['curves'][:, c])
        D0 = np.stack([curve(logE[..., c], c) for c in range(3)], -1)
        if dir_amount == 0.0:
            return D0
        L = D0 / self.neg_gamma                 # density expressed in log-exposure units
        w = dir_w if dir_w is not None else DIR_WEIGHTS
        delta = np.zeros_like(L)
        for c in range(3):
            for k in range(3):
                if k != c:
                    delta[..., c] -= dir_amount * w[c, k] * (L[..., k] - L[..., c])
        logE2 = logE + delta
        return np.stack([curve(logE2[..., c], c) for c in range(3)], -1)

    # ----- stage: print -----
    def print_exposure(self, Dneg, points=(25, 25, 25)):
        T = 10.0 ** -(Dneg @ self.neg['dyes'].T + self.neg['base'])   # (N, wl)
        Hbk = np.einsum('nl,bkl->nbk', T, self.W)                      # light per band per print layer
        g = 10.0 ** (self.log_gain + (np.asarray(points, float) - NOMINAL_POINTS) * POINT)
        return np.einsum('nbk,b->nk', Hbk, g)

    def develop_print(self, H, contrast=1.0, pivot=None):
        le = self.prt['log_exposure']
        logH = np.log10(np.maximum(H, 1e-9))
        out = []
        for c in range(3):
            x = logH[..., c]
            if contrast != 1.0:
                pv = self.pivot[c]
                x = pv + (x - pv) * contrast
            out.append(np.interp(x, le, self.prt['curves'][:, c]))
        return np.stack(out, -1)

    def project(self, Dp, bleach_bypass=0.0):
        dens = Dp @ self.prt['dyes'].T + self.prt['base']
        if bleach_bypass > 0:   # retained silver: spectrally neutral, proportional to developed dye
            dens = dens + bleach_bypass * BB_SILVER * Dp.mean(-1, keepdims=True)
        T = 10.0 ** -dens
        return T @ self.proj_xyz   # D65 XYZ, white = 1

    # ----- full chain -----
    def render(self, lin_dwg, points=(25, 25, 25), dir_amount=0.0, push=0.0, print_contrast=1.0, bleach=0.0):
        E = self.exposure(lin_dwg)
        Dn = self.develop_negative(E, dir_amount, push=push)
        H = self.print_exposure(Dn, points)
        Dp = self.develop_print(H, print_contrast)
        return self.project(Dp, bleach)


DIR_WEIGHTS = np.array([[0.0, 0.5, 0.5],
                        [0.5, 0.0, 0.5],
                        [0.5, 0.5, 0.0]])
BB_SILVER = 0.35   # retained silver density per unit mean dye density at full bleach bypass


# ---------- calibration ----------
def training_reflectances(wl, n=1500, seed=3):
    """Realistic surface spectra: broad positive bumps and edges over a floor, plus two ColorChecker
    measurements. Used to fit the camera stage (scene DWG -> film layer exposures)."""
    rng = np.random.default_rng(seed)
    x = (wl - 380.0) / 400.0
    out = []
    while len(out) < n:
        r = np.full_like(x, rng.uniform(0.02, 0.3))
        for _ in range(rng.integers(1, 4)):
            if rng.random() < 0.5:
                c, w = rng.uniform(0, 1), rng.uniform(0.06, 0.35)
                r = r + rng.uniform(0.1, 0.8) * np.exp(-0.5 * ((x - c) / w) ** 2)
            else:
                c, k = rng.uniform(0.15, 0.85), rng.uniform(8, 40) * rng.choice([-1, 1])
                r = r + rng.uniform(0.1, 0.7) / (1 + np.exp(-k * (x - c)))
        out.append(np.clip(r, 0.01, 1.0) * rng.uniform(0.3, 1.0))
    for name in ('BabelColor Average', 'ColorChecker N Ohta'):
        for sd in colour.SDS_COLOURCHECKERS[name].values():
            out.append(np.interp(wl, sd.wavelengths, sd.values))
    return np.array(out)


EXPOSURE_FLOOR = 0.003   # smooth lower bound per layer, as a fraction of the pixel's mean exposure


def soft_floor(E):
    """Real light never drives a layer's exposure negative; saturated inputs can, through the fitted map.
    Replace the hard clamp with a smooth floor relative to the pixel's overall exposure."""
    T = np.maximum(E, 0).mean(-1, keepdims=True)
    f = EXPOSURE_FLOOR * T
    return 0.5 * (E + np.sqrt(E * E + 4.0 * f * f))


def rootpoly(rgb):
    """Scale-invariant second-order features in the spirit of root-polynomial colour correction
    (Finlayson et al. 2015), using pairwise harmonic means instead of square roots: same degree-1
    homogeneity (exposure scales exactly with light), exact on neutrals, but finite slope near zero,
    which avoids folds on very saturated colours."""
    rgb = np.atleast_2d(rgb)
    r, g, b = np.clip(rgb, 0, None).T
    hm = lambda a, c: 2.0 * a * c / np.maximum(a + c, 1e-12)
    return np.column_stack([rgb, hm(r, g), hm(g, b), hm(r, b)])


def fit_camera(chain):
    """Root-polynomial map from linear DWG to the negative's layer exposures, fitted on reflectances.

    The camera is assumed white-balanced: a surface's colour under D65 is what arrives as DWG,
    while the film sees the same surface under its rated illuminant (3200K or D55).
    Neutrals map exactly (the root terms equal r=g=b on the grey axis); 18% grey -> exposure 1."""
    wl = chain.wl
    R = training_reflectances(wl)
    d65 = fd.illuminant('D65', wl)
    rgb = ((R * d65) @ chain.cmf / (d65 @ chain.cmf[:, 1])) @ XYZ_TO_DWG.T
    E = (R * chain.ref_ill) @ chain.neg_sens
    F = rootpoly(rgb)
    w = 1.0 / np.maximum(E, 1e-6 * E.max(0))          # fit relative (log-like) error
    M = np.stack([np.linalg.lstsq(F * w[:, c:c + 1], E[:, c] * w[:, c], rcond=None)[0] for c in range(3)])
    M = M / (rootpoly(np.full(3, 0.18)) @ M.T)[0][:, None]
    chain.cam = M
    chain.fit_data = (rgb, E)
    return M


def balance_printer(chain, dir_amount=0.0):
    """Solve printer band gains so 18% grey at normal exposure prints neutral at the LAD aim."""
    from scipy.optimize import least_squares
    grey = np.full((1, 3), 0.18)
    # target: D65-neutral at luminance of a print of visual density ~1.0 relative to projector light
    clear_Y = (np.ones_like(chain.wl) @ chain.proj_xyz)[1]   # projector with no film, relative to base white
    target = np.array(colour.xy_to_XYZ(D65_xy)) * clear_Y * 10.0 ** -LAD_PRINT_DENSITY

    def resid(lg):
        chain.log_gain = lg
        out = chain.render(grey, dir_amount=dir_amount)[0]
        return np.log10(np.maximum(out, 1e-9)) - np.log10(target)

    sol = least_squares(resid, np.zeros(3), xtol=1e-12, ftol=1e-12)
    chain.log_gain = sol.x
    # pivot for print-contrast control: the print log exposure of the LAD grey
    Dn = chain.develop_negative(chain.exposure(grey), dir_amount)
    chain.pivot = np.log10(chain.print_exposure(Dn)[0])
    return sol.x, sol.fun


