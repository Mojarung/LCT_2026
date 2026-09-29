/** Surface-gradient bump mapping in view space. Height is in metres; derivatives
 * fade subpixel detail naturally, without tessellation or an extra normal texture. */
export const RELIEF_NORMAL = /* glsl */ `
vec3 reliefNormal(vec3 surfacePosition, vec3 surfaceNormal, float height) {
  vec3 dx = dFdx(surfacePosition);
  vec3 dy = dFdy(surfacePosition);
  vec3 rx = cross(dy, surfaceNormal);
  vec3 ry = cross(surfaceNormal, dx);
  float determinant = dot(dx, rx);
  vec3 gradient = sign(determinant) * (dFdx(height) * rx + dFdy(height) * ry);
  return normalize(max(abs(determinant), 1e-8) * surfaceNormal - gradient);
}
`;
