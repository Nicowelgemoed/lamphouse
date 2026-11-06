import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import harness, model as m, config
from PIL import Image

def render(params, out_png, dctl=config.OUT_STANDALONE, frame=1, scene=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scene_dwg.npy')):
    img = m.di_encode(np.load(scene))
    t = time.time()
    o = harness.run(dctl, img.astype(np.float32), params, frame=frame)
    Image.fromarray((np.clip(o, 0, 1) * 255 + 0.5).astype(np.uint8)).save(out_png)
    return o, time.time() - t

if __name__ == '__main__':
    import json
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    o, dt = render(params, sys.argv[1])
    print('rendered in %.1fs' % dt)
