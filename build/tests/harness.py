"""Compile the DCTL as plain C on the CPU and run it over an image, so the shipped kernel can be
compared number-for-number with the Python model. DCTL built-ins are mapped to libm."""
import re, subprocess, os, numpy as np

PRELUDE = r'''
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { float x, y, z; } float3;
static inline float3 make_float3(float a, float b, float c) { float3 r = {a, b, c}; return r; }
#define __DEVICE__ static
#define __CONSTANT__ static const
#define __CONSTANTREF__ const
#define __TEXTURE__ const float*
static int G_W;
static int G_FRAME = 1;
#define _tex2D(t, x, y) ((t)[(y) * G_W + (x)])
#define _fabs fabsf
#define _powf powf
#define _logf logf
#define _log2f log2f
#define _log10f log10f
#define _expf expf
#define _exp2f exp2f
#define _exp10f(x) powf(10.0f, (x))
#define _fmaxf fmaxf
#define _fminf fminf
#define _sqrtf sqrtf
#define _floorf floorf
#define _cosf cosf
#define _sinf sinf
#define _round roundf
static inline float _clampf(float x, float a, float b) { return x < a ? a : (x > b ? b : x); }
static inline float _saturatef(float x) { return _clampf(x, 0.0f, 1.0f); }
'''


def dctl_to_c(src, params):
    """UI parameters and TIMELINE_FRAME_INDEX become locals of transform(), as on Resolve's GPU builds,
    so a helper function that reads them fails to compile here too."""
    out, enums, locals_ = [], [], []
    for line in src.splitlines():
        if line.startswith('DEFINE_UI_TOOLTIP'):
            continue
        mm = re.match(r'DEFINE_UI_PARAMS\((\w+),[^,]*,\s*(\w+),\s*([-\d.]+)(.*)\)\s*$', line)
        if mm:
            name, kind, default, rest = mm.groups()
            if kind == 'DCTLUI_COMBO_BOX':
                names = [x.strip() for x in re.search(r'\{([^}]*)\}', rest).group(1).split(',')]
                for i, n in enumerate(names):
                    enums.append('#define %s %d' % (n, i))
                locals_.append('const int %s = %s;' % (name, params.get(name, int(float(default)))))
            elif kind == 'DCTLUI_CHECK_BOX':
                locals_.append('const int %s = %s;' % (name, params.get(name, int(float(default)))))
            else:
                locals_.append('const float %s = %sf;' % (name, params.get(name, float(default))))
            continue
        out.append(line)
    body = '\n'.join(out)
    m = re.search(r'__DEVICE__ float3 transform\([^)]*\)\s*\{', body)
    locals_.append('const int TIMELINE_FRAME_INDEX = G_FRAME;')
    body = body[:m.end()] + '\n' + '\n'.join(locals_) + '\n' + body[m.end():]
    return PRELUDE + '\n'.join(enums) + '\n' + body


MAIN = r'''
int main(int argc, char** argv) {
    int w = atoi(argv[1]), h = atoi(argv[2]);
    G_W = w;
    size_t n = (size_t)w * h;
    float* r = malloc(n * 4); float* g = malloc(n * 4); float* b = malloc(n * 4);
    FILE* f = fopen(argv[3], "rb");
    fread(r, 4, n, f); fread(g, 4, n, f); fread(b, 4, n, f); fclose(f);
    float* o = malloc(n * 12);
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
        float3 v = transform(w, h, x, y, r, g, b);
        size_t i = ((size_t)y * w + x) * 3;
        o[i] = v.x; o[i + 1] = v.y; o[i + 2] = v.z;
    }
    f = fopen(argv[4], "wb"); fwrite(o, 4, n * 3, f); fclose(f);
    return 0;
}
'''


def run(dctl_path, img_di, params=None, frame=1, workdir='/tmp/claude-0/dctl_harness'):
    """img_di: (H, W, 3) DaVinci Intermediate encoded input. Returns (H, W, 3) DCTL output."""
    os.makedirs(workdir, exist_ok=True)
    params = dict(params or {})
    c = dctl_to_c(open(dctl_path).read(), params).replace('static int G_FRAME = 1;', 'static int G_FRAME = %d;' % frame)
    import hashlib
    key = hashlib.md5(c.encode()).hexdigest()[:12]
    src, exe = f'{workdir}/k{key}.c', f'{workdir}/k{key}'
    if not os.path.exists(exe):
        open(src, 'w').write(c + MAIN)
        r = subprocess.run(['gcc', '-O2', '-w', '-o', exe, src, '-lm'], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[:3000])
    h, w, _ = img_di.shape
    np.ascontiguousarray(img_di.transpose(2, 0, 1), dtype=np.float32).tofile(f'{workdir}/in.bin')
    subprocess.run([exe, str(w), str(h), f'{workdir}/in.bin', f'{workdir}/out.bin'], check=True)
    return np.fromfile(f'{workdir}/out.bin', dtype=np.float32).reshape(h, w, 3)
