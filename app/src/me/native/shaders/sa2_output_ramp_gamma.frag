// Output pass with the game's gamma ramp (sa2_native_ramp_gamma) and FXAA (ds2_output_fxaa). ds2scholar-nx (2026-10-25):
// recovered from the SPIR-V of sa2-nx (sa2_output_ramp_gamma_ps.h had no source in any tree; spirv-dis of the original,
// names kept) and extended with kFxaaCalidad (ds2_output_fxaa_quality): FXAA 3.11 Quality (Timothy Lottes) with an
// edge search along the span instead of the light 4-tap variant. With kFxaaCalidad false the code is the original's.
// Build: tools/win/build_output_shader.ps1.
#version 450

layout(set = 0, binding = 0) uniform texture2D origen;
layout(set = 0, binding = 1) uniform sampler muestreador;
layout(set = 0, binding = 2) uniform Rampa {
  vec4 entradas[256];
  vec4 mezcla;   // x saturation, y vibrance, z 1 / gamma
  vec4 efectos;  // x vignette, y scanlines
} rampa;
layout(push_constant) uniform Constantes {
  layout(offset = 16) ivec2 desplazamiento;
  layout(offset = 24) vec2 inverso;
} constantes;

layout(constant_id = 0) const bool kExacta = false;
layout(constant_id = 1) const bool kGraduacion = false;
layout(constant_id = 2) const bool kFxaa = false;
layout(constant_id = 3) const bool kFxaaCalidad = false;

layout(location = 0) out vec4 color;

vec3 Muestra(vec2 uv) {
  return textureLod(sampler2D(origen, muestreador), uv, 0.0).rgb;
}

float Luma(vec2 uv) {
  return dot(Muestra(uv), vec3(0.299, 0.587, 0.114));
}

// FXAA 3.11 Quality, preset 12 (5 search steps), thresholds of the "high quality" settings: edge 0.125, minimum 0.0312,
// subpixel 0.75. Luma from RGB (the frame has no luma in alpha).
vec3 FxaaCalidad(vec2 pos, vec2 rcp) {
  const float kUmbral = 0.125, kUmbralMin = 0.0312, kSubpix = 0.75;
  const float kPasos[5] = float[5](1.0, 1.5, 2.0, 4.0, 12.0);
  vec3 rgbM = Muestra(pos);
  float lumaM = dot(rgbM, vec3(0.299, 0.587, 0.114));
  float lumaS = Luma(pos + vec2(0.0, 1.0) * rcp);
  float lumaE = Luma(pos + vec2(1.0, 0.0) * rcp);
  float lumaN = Luma(pos + vec2(0.0, -1.0) * rcp);
  float lumaW = Luma(pos + vec2(-1.0, 0.0) * rcp);
  float rangeMax = max(max(lumaN, lumaW), max(lumaE, max(lumaS, lumaM)));
  float rangeMin = min(min(lumaN, lumaW), min(lumaE, min(lumaS, lumaM)));
  float range = rangeMax - rangeMin;
  if (range < max(kUmbralMin, rangeMax * kUmbral)) {
    return rgbM;
  }
  float lumaNW = Luma(pos + vec2(-1.0, -1.0) * rcp);
  float lumaSE = Luma(pos + vec2(1.0, 1.0) * rcp);
  float lumaNE = Luma(pos + vec2(1.0, -1.0) * rcp);
  float lumaSW = Luma(pos + vec2(-1.0, 1.0) * rcp);
  float lumaNS = lumaN + lumaS;
  float lumaWE = lumaW + lumaE;
  float edgeHorz1 = -2.0 * lumaM + lumaNS;
  float edgeVert1 = -2.0 * lumaM + lumaWE;
  float lumaNESE = lumaNE + lumaSE;
  float lumaNWNE = lumaNW + lumaNE;
  float edgeHorz2 = -2.0 * lumaE + lumaNESE;
  float edgeVert2 = -2.0 * lumaN + lumaNWNE;
  float lumaNWSW = lumaNW + lumaSW;
  float lumaSWSE = lumaSW + lumaSE;
  float edgeHorz3 = -2.0 * lumaW + lumaNWSW;
  float edgeVert3 = -2.0 * lumaS + lumaSWSE;
  float edgeHorz = abs(edgeHorz3) + abs(edgeHorz1) * 2.0 + abs(edgeHorz2);
  float edgeVert = abs(edgeVert3) + abs(edgeVert1) * 2.0 + abs(edgeVert2);
  bool horzSpan = edgeHorz >= edgeVert;
  float lengthSign = horzSpan ? rcp.y : rcp.x;
  if (!horzSpan) {
    lumaN = lumaW;
    lumaS = lumaE;
  }
  float subpixB = ((lumaNS + lumaWE) * 2.0 + (lumaNWSW + lumaNESE)) * (1.0 / 12.0) - lumaM;
  float gradientN = lumaN - lumaM;
  float gradientS = lumaS - lumaM;
  float lumaNN = lumaN + lumaM;
  float lumaSS = lumaS + lumaM;
  bool pairN = abs(gradientN) >= abs(gradientS);
  float gradient = max(abs(gradientN), abs(gradientS));
  if (pairN) lengthSign = -lengthSign;
  float subpixC = clamp(abs(subpixB) / range, 0.0, 1.0);
  vec2 posB = pos;
  vec2 offNP = horzSpan ? vec2(rcp.x, 0.0) : vec2(0.0, rcp.y);
  if (horzSpan) {
    posB.y += lengthSign * 0.5;
  } else {
    posB.x += lengthSign * 0.5;
  }
  if (!pairN) lumaNN = lumaSS;
  float gradientScaled = gradient * 0.25;
  bool lumaMLTZero = lumaM - lumaNN * 0.5 < 0.0;
  vec2 posN = posB - offNP * kPasos[0];
  vec2 posP = posB + offNP * kPasos[0];
  float lumaEndN = Luma(posN) - lumaNN * 0.5;
  float lumaEndP = Luma(posP) - lumaNN * 0.5;
  bool doneN = abs(lumaEndN) >= gradientScaled;
  bool doneP = abs(lumaEndP) >= gradientScaled;
  for (int i = 1; i < 5 && !(doneN && doneP); ++i) {
    if (!doneN) {
      posN -= offNP * kPasos[i];
      lumaEndN = Luma(posN) - lumaNN * 0.5;
      doneN = abs(lumaEndN) >= gradientScaled;
    }
    if (!doneP) {
      posP += offNP * kPasos[i];
      lumaEndP = Luma(posP) - lumaNN * 0.5;
      doneP = abs(lumaEndP) >= gradientScaled;
    }
  }
  float dstN = horzSpan ? pos.x - posN.x : pos.y - posN.y;
  float dstP = horzSpan ? posP.x - pos.x : posP.y - pos.y;
  bool goodSpanN = (lumaEndN < 0.0) != lumaMLTZero;
  bool goodSpanP = (lumaEndP < 0.0) != lumaMLTZero;
  bool directionN = dstN < dstP;
  float dst = min(dstN, dstP);
  bool goodSpan = directionN ? goodSpanN : goodSpanP;
  float pixelOffset = dst * (-1.0 / (dstP + dstN)) + 0.5;
  float subpixF = (-2.0 * subpixC + 3.0) * subpixC * subpixC;
  float subpixH = subpixF * subpixF * kSubpix;
  float pixelOffsetSubpix = max(goodSpan ? pixelOffset : 0.0, subpixH);
  if (horzSpan) {
    pos.y += pixelOffsetSubpix * lengthSign;
  } else {
    pos.x += pixelOffsetSubpix * lengthSign;
  }
  return Muestra(pos);
}

vec3 Fxaa(vec2 uv) {
  vec2 paso = constantes.inverso;
  vec3 rgb_centro = textureLod(sampler2D(origen, muestreador), uv, 0.0).rgb;
  float luma_centro = dot(rgb_centro, vec3(0.299, 0.587, 0.114));
  float luma_no = Luma(uv + vec2(-paso.x, -paso.y));
  float luma_ne = Luma(uv + vec2(paso.x, -paso.y));
  float luma_so = Luma(uv + vec2(-paso.x, paso.y));
  float luma_se = Luma(uv + vec2(paso.x, paso.y));
  float luma_min = min(luma_centro, min(min(luma_no, luma_ne), min(luma_so, luma_se)));
  float luma_max = max(luma_centro, max(max(luma_no, luma_ne), max(luma_so, luma_se)));
  if (luma_max - luma_min < max(0.0833, luma_max * 0.166)) {
    return rgb_centro;
  }
  vec2 direccion = vec2(-((luma_no + luma_ne) - (luma_so + luma_se)), (luma_no + luma_so) - (luma_ne + luma_se));
  float reduccion = max((luma_no + luma_ne + luma_so + luma_se) * 0.03125, 0.0078125);
  float inversa_min = 1.0 / (min(abs(direccion.x), abs(direccion.y)) + reduccion);
  direccion = clamp(direccion * inversa_min, vec2(-8.0), vec2(8.0)) * paso;
  vec3 rgb_a = 0.5 * (textureLod(sampler2D(origen, muestreador), uv + direccion * -0.166666672, 0.0).rgb +
                      textureLod(sampler2D(origen, muestreador), uv + direccion * 0.166666672, 0.0).rgb);
  vec3 rgb_b = rgb_a * 0.5 + 0.25 * (textureLod(sampler2D(origen, muestreador), uv + direccion * -0.5, 0.0).rgb +
                                     textureLod(sampler2D(origen, muestreador), uv + direccion * 0.5, 0.0).rgb);
  float luma_b = dot(rgb_b, vec3(0.299, 0.587, 0.114));
  return (luma_b < luma_min || luma_b > luma_max) ? rgb_a : rgb_b;
}

void main() {
  ivec2 pixel = ivec2(gl_FragCoord.xy) - constantes.desplazamiento;
  vec3 texel;
  if (kFxaa) {
    vec2 uv = (vec2(uvec2(pixel)) + 0.5) * constantes.inverso;
    texel = kFxaaCalidad ? FxaaCalidad(uv, constantes.inverso) : Fxaa(uv);
  } else if (kExacta) {
    texel = texelFetch(sampler2D(origen, muestreador), pixel, 0).rgb;
  } else {
    texel = textureLod(sampler2D(origen, muestreador), (vec2(uvec2(pixel)) + 0.5) * constantes.inverso, 0.0).rgb;
  }
  uvec3 i = uvec3(clamp(texel, 0.0, 1.0) * 255.0 + 0.5);
  vec3 c = vec3(rampa.entradas[i.x].x, rampa.entradas[i.y].y, rampa.entradas[i.z].z);
  if (kGraduacion) {
    float luma = dot(max(c, vec3(0.0)), vec3(0.2126, 0.7152, 0.0722));
    c = mix(vec3(luma), c, vec3(rampa.mezcla.x));
    float saturado = max(c.x, max(c.y, c.z)) - min(c.x, min(c.y, c.z));
    c = mix(vec3(luma), c, vec3(1.0 + rampa.mezcla.y * (1.0 - clamp(saturado, 0.0, 1.0))));
    c = pow(max(c, vec3(9.99999975e-05)), vec3(rampa.mezcla.z));
    vec2 uv = (vec2(uvec2(pixel)) + 0.5) * constantes.inverso;
    float v = rampa.efectos.x;
    c *= (1.0 - v * max(0.0, 1.0 - uv.y / 0.42)) * (1.0 - v * max(0.0, 1.0 - (1.0 - uv.y) / 0.42)) *
         (1.0 - v * max(0.0, 1.0 - uv.x / 0.42)) * (1.0 - v * max(0.0, 1.0 - (1.0 - uv.x) / 0.42));
    if (uint(pixel.y) % 3u == 0u) {
      c *= 1.0 - rampa.efectos.y * 0.7;
    }
    c = clamp(c, vec3(0.0), vec3(1.0));
  }
  color = vec4(c, 1.0);
}
