"""Unit tests use small synthetic HLSL fragments, no game containers."""
import unittest

from ds2_shader_light import TARGETS, transform


class LightShaders(unittest.TestCase):
    def test_majula_passes_share_one_mask(self):
        self.assertEqual(TARGETS.get('0feaa33b192cdc87'), 16)
        self.assertEqual(TARGETS.get('caee55f06defe9d8'), 16)

    def test_unknown_shader_rejected(self):
        with self.assertRaises(ValueError):
            transform('0' * 16, 'void main() {}')

    def test_missing_patch_sites_rejected(self):
        for key in TARGETS:
            with self.subTest(key=key), self.assertRaises(ValueError):
                transform(key, 'void main() {}')

    def test_transform_keeps_original_in_else(self):
        # Minimal excerpts representing the four transformations.
        fragments = {
            '0feaa33b192cdc87': ('r9.xyz = tfetch2D(g_DiffuseMap2_a).xyz;\n'
                               'r0.z = tfetch2D(g_BumpMap2_a).z;\n'
                               'r3.w = r3.y * r7.w + r3.x;\n'
                               'r2.xyzw = r9.xyzw * r7.wwww + r2.xyzw;'),
            'caee55f06defe9d8': ('r9.xyz = tfetch2D(g_BumpMap2_a).xyw;\n'
                               'r0.yzw = r0.xzy * r7.www + r2.xzy;'),
            '04762adf6a086695': 'if (p0)\n\t{\n\t\tr5.xyzw = tfetch2D(DiffuseSampler_a);\n\t}\n',
            '3c14b756c88a2b7f': 'ps = clamp(log2(abs(r0.x)), FLT_MIN, FLT_MAX);\n\tr0.x = ps;\n\tr1.xyz = FC_PrecisionParam.xxx * FC_FinalColorMult.xyz;\n\tps = FC_FogCol.w * r0.x;\n\tr0.x = ps;\n\tr2.xyz = -r0.yzw + FC_FogCol.xyz;\n\tps = exp2(r0.x);',
            '41db93b1dec497de': 'r0.xyz = select(r7.xyz == 0.0, r6.xyz, r0.xyz);',
            '9942495d3b412155': ('r8.y = tfetch2D(g_BumpMap2_a).z;\n'
                               'r8.zw = tfetch2D(g_SpecularMap2_a).xy;\n'
                               'r11.xyz = tfetch2D(g_DiffuseMap2_a).xyz;\n'
                               'r0.x = tfetch2D(g_BlendMap_a).y;\n'
                               'r9.x = saturate(select(r4.w > 0.0, r4.z, r4.x));'),
        }
        for key, source in fragments.items():
            source = '#ifndef __spirv__\n[shader("pixel")]\n#endif\n' + source
            with self.subTest(key=key):
                self.assertIn(key, TARGETS)
                patched = transform(key, source)
                self.assertIn('DS2_SHADER_LIGHT', patched)
                self.assertIn('1u << 23', patched)
                if key in ('0feaa33b192cdc87', 'caee55f06defe9d8'):
                    self.assertIn('r9.xyz = 0.0;', patched)
                if key == '0feaa33b192cdc87':
                    self.assertIn('r3.w = r3.x;', patched)  # first material channel, not another swizzle
                    self.assertIn('r2.xyzw = r2.xyzw;', patched)  # keep the first sampled diffuse
                if key == 'caee55f06defe9d8':
                    self.assertIn('r0.yzw = r2.xzy;', patched)  # first reconstructed normal's lane order
                # The tool must retain the original path verbatim in the else branch.
                self.assertIn('#else\n', patched)
                for line in source.splitlines():
                    self.assertIn(line, patched)
                with self.assertRaises(ValueError):
                    transform(key, patched)


if __name__ == '__main__':
    unittest.main()
