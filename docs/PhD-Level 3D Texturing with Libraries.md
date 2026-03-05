# PhD-Level 3D Texturing with Libraries

---

## I. The Library Landscape: A Taxonomy

Before diving deep, understand that 3D texturing libraries stratify into four architectural layers, each with distinct responsibilities:

| Layer                     | Responsibility                                  | Representative Libraries                                     |
| ------------------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| **GPU Runtime**           | Texture objects, samplers, compression hardware | OpenGL, Vulkan, DirectX 12, Metal                            |
| **Math/Geometry**         | Mesh parameterization, UV computation           | libigl, CGAL, OpenMesh, Geometry Central                     |
| **Asset Pipeline**        | Baking, conversion, format I/O                  | Substance Automation Toolkit, xAtlas, OpenImageIO, MaterialX |
| **Rendering Integration** | Material systems, shader binding                | USD/Hydra, OSL, MDL, Three.js, Filament                      |

A PhD-level practitioner understands not just what each library does, but **why its API is shaped the way it is** — the mathematical and architectural constraints that force its design decisions.

---

## II. GPU Texture APIs: The Hardware Contract

### 2.1 OpenGL: The Historical Foundation

OpenGL's texture API exposes the GPU's **texture unit** abstraction — a hardware sampler that sits between the shader and texture memory. Understanding its design reveals the hardware constraints.

**Texture Object Lifecycle:**

```c
GLuint tex;
glGenTextures(1, &tex);               // allocate name
glBindTexture(GL_TEXTURE_2D, tex);    // bind to active unit
glTexImage2D(GL_TEXTURE_2D,
    0,                                // mip level 0 (base)
    GL_RGBA8,                         // internal format (GPU storage)
    width, height, 0,
    GL_RGBA, GL_UNSIGNED_BYTE,        // source format
    pixels);
glGenerateMipmap(GL_TEXTURE_2D);      // generate full mip chain
```

The **internal format** vs. **source format** distinction is architecturally critical and frequently misunderstood. The internal format (`GL_RGBA8`) is what the GPU allocates and stores in VRAM. The source format (`GL_RGBA, GL_UNSIGNED_BYTE`) describes the CPU-side data you're uploading. The driver performs conversion during upload. This matters because:

- `GL_RGBA8` → 8-bit unorm per channel (sRGB _not_ assumed)
- `GL_SRGB8_ALPHA8` → GPU performs sRGB→linear conversion on _read_, not on write
- `GL_RGBA16F` → half-float, used for HDR/emissive
- `GL_COMPRESSED_RGBA_BPTC_UNORM` → BC7 hardware compression

**The sRGB gamma pipeline** is a pervasive source of errors. Albedo textures authored in sRGB color space must be declared as `GL_SRGB8_ALPHA8` — the GPU's texture sampler then automatically linearizes them before the fragment shader runs. If you declare sRGB textures as `GL_RGBA8`, you get **double gamma** — the math operates on perceptually-encoded values, causing physically wrong BRDF evaluations that look "washed out."

**Sampler Objects** (OpenGL 3.3+) decouple sampling parameters from texture objects:

```c
GLuint sampler;
glGenSamplers(1, &sampler);
glSamplerParameteri(sampler, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
glSamplerParameteri(sampler, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
glSamplerParameterf(sampler, GL_TEXTURE_MAX_ANISOTROPY, 16.0f);
glSamplerParameteri(sampler, GL_TEXTURE_WRAP_S, GL_REPEAT);
glBindSampler(texture_unit, sampler);
```

`GL_LINEAR_MIPMAP_LINEAR` = trilinear filtering (bilinear within each mip level + linear interpolation _between_ mip levels). This is the standard production setting. `GL_LINEAR_MIPMAP_NEAREST` = bilinear only (no inter-mip interpolation) — causes visible mip "pops," never use in production.

**Bindless Textures** (`GL_ARB_bindless_texture`): Traditional texture binding has a hard limit of 16–32 texture units simultaneously. For scenes with thousands of unique materials, this requires expensive rebinding. Bindless textures assign each texture a 64-bit GPU handle (a virtual address into VRAM), passable directly to shaders as a `uvec2` uniform. The shader casts it to `sampler2D` at runtime:

```glsl
uniform uvec2 textureHandle;
// ...
vec4 color = texture(sampler2D(textureHandle), uv);
```

This eliminates the texture unit bottleneck entirely — you can bind effectively unlimited textures per draw call.

### 2.2 Vulkan: Explicit Texture Management

Vulkan exposes the full hardware abstraction. There are no implicit state machines — every resource and its usage must be declared explicitly. This is architecturally important for understanding what OpenGL was hiding.

**Image → ImageView → Sampler**: Vulkan separates three concerns that OpenGL merged:

```cpp
// 1. VkImage: raw memory allocation + format declaration
VkImageCreateInfo imageInfo{};
imageInfo.imageType     = VK_IMAGE_TYPE_2D;
imageInfo.format        = VK_FORMAT_R8G8B8A8_SRGB;
imageInfo.extent        = {width, height, 1};
imageInfo.mipLevels     = mipLevels;
imageInfo.arrayLayers   = 1;
imageInfo.usage         = VK_IMAGE_USAGE_TRANSFER_DST_BIT
                        | VK_IMAGE_USAGE_SAMPLED_BIT;
vkCreateImage(device, &imageInfo, nullptr, &image);

// 2. VkImageView: interpretation of the image (subresource range)
VkImageViewCreateInfo viewInfo{};
viewInfo.image            = image;
viewInfo.viewType         = VK_IMAGE_VIEW_TYPE_2D;
viewInfo.format           = VK_FORMAT_R8G8B8A8_SRGB;
viewInfo.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, mipLevels, 0, 1};
vkCreateImageView(device, &viewInfo, nullptr, &imageView);

// 3. VkSampler: sampling parameters
VkSamplerCreateInfo samplerInfo{};
samplerInfo.magFilter        = VK_FILTER_LINEAR;
samplerInfo.minFilter        = VK_FILTER_LINEAR;
samplerInfo.mipmapMode       = VK_SAMPLER_MIPMAP_MODE_LINEAR;
samplerInfo.anisotropyEnable = VK_TRUE;
samplerInfo.maxAnisotropy    = 16.0f;
vkCreateSampler(device, &samplerInfo, nullptr, &sampler);
```

**Image Layout Transitions** are the most Vulkan-specific concept with no OpenGL equivalent. GPU memory is accessed differently depending on its usage — a texture being written to (as a render target) is in a different hardware cache configuration than one being sampled in a shader. `VkImageLayout` encodes this:

- `VK_IMAGE_LAYOUT_UNDEFINED` → don't care (initial state, contents undefined)
- `VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL` → receiving data from CPU
- `VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL` → being sampled in shaders
- `VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL` → being rendered into

Transitioning layouts requires a **pipeline barrier** — a GPU synchronization primitive that flushes caches and inserts a memory dependency:

```cpp
VkImageMemoryBarrier barrier{};
barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
// ...
vkCmdPipelineBarrier(cmdBuffer,
    VK_PIPELINE_STAGE_TRANSFER_BIT,
    VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
    0, 0, nullptr, 0, nullptr, 1, &barrier);
```

This explicit synchronization is what enables Vulkan's performance — you as the programmer assert exactly when data is ready, eliminating driver-side hazard tracking.

**Descriptor Sets** bind textures to shaders. A `VkDescriptorSet` is a handle to a collection of resource bindings (uniform buffers, samplers, images). The descriptor set layout declares the _schema_; descriptor sets carry the _actual resource handles_:

```cpp
VkDescriptorImageInfo imageInfo{};
imageInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
imageInfo.imageView   = textureImageView;
imageInfo.sampler     = textureSampler;

VkWriteDescriptorSet write{};
write.dstSet          = descriptorSet;
write.dstBinding      = 1;  // binding=1 in GLSL
write.descriptorType  = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
write.pImageInfo      = &imageInfo;
vkUpdateDescriptorSets(device, 1, &write, 0, nullptr);
```

---

## III. libigl: Geometry Processing for UV Parameterization

**libigl** (Alec Jacobson et al., ETH Zürich) is the gold standard academic/production geometry processing library. Its header-only C++ design means every algorithm is inspectable source code — critical for PhD-level understanding.

### 3.1 Core Data Structures

libigl uses **Eigen matrices** as its universal mesh representation:

```cpp
Eigen::MatrixXd V;  // n×3 vertex positions
Eigen::MatrixXi F;  // m×3 face indices (triangle soup)
```

This is the simplest possible representation — no half-edge structure, no connectivity overhead. Many algorithms only need V and F. The downside: adjacency queries (vertex neighbors, edge lists) require recomputation. libigl caches these in `igl::adjacency_list`, `igl::edge_topology`, etc.

### 3.2 LSCM Parameterization

```cpp
#include <igl/lscm.h>

// Fix two boundary vertices to break rotational/translational DOF
Eigen::VectorXi b(2);
b(0) = 0; b(1) = n_boundary_vertices - 1;

Eigen::MatrixXd bc(2, 2);
bc << 0, 0,   // UV of first fixed vertex
      1, 0;   // UV of second fixed vertex

Eigen::MatrixXd UV;
igl::lscm(V, F, b, bc, UV);
```

What happens internally: libigl assembles the **cotangent Laplacian** `L` and the **mass matrix** `M`, then formulates LSCM as a sparse linear system **A·u = b** where u ∈ ℝ^{2n} stacks (U, V) coordinates. The cotangent weights **w_ij = (cot α_ij + cot β_ij)/2** come from the angles opposite to edge (i,j) in adjacent triangles. The system is solved with `Eigen::SimplicialLDLT` — a sparse Cholesky factorization that exploits the positive semi-definiteness of L.

**Why cotangent weights?** The cotangent Laplacian is the discrete approximation of the **Laplace-Beltrami operator** on triangle meshes — it's the correct intrinsic operator that converges to the smooth operator as mesh resolution increases. Using uniform weights (1/degree) gives a graph Laplacian that depends on mesh connectivity, not geometry — physically wrong for curved surfaces.

### 3.3 ARAP (As-Rigid-As-Possible)

ARAP is an iterative algorithm that alternates between:

1. **Local step**: For each triangle, find the closest rotation **R_t** to the current Jacobian **J_t** (closed-form via SVD: **R_t = UV^T** from SVD of **J_t = UΣV^T**)
2. **Global step**: Solve a linear system to find UV coordinates that minimize the sum of squared deviations from these local rotations

```cpp
#include <igl/arap.h>

igl::ARAPData arap_data;
arap_data.energy = igl::ARAP_ENERGY_TYPE_SPOKES_AND_RIMS;
igl::arap_precomputation(V, F, 2, b, arap_data);

Eigen::MatrixXd UV_init = UV_lscm; // initialize with LSCM result
igl::arap_solve(bc, arap_data, UV_init);
```

The `precomputation` step factorizes the global step's linear system (which doesn't change between iterations — only the RHS changes). This amortizes the expensive Cholesky factorization over all iterations, making each iteration cheap.

**Convergence**: ARAP is a **block coordinate descent** on the combined energy over (UV, {R_t}). Each step provably decreases the energy. However, it's non-convex — initialization matters. LSCM provides a good initialization that avoids bad local minima.

### 3.4 Geodesic Distance and Seam Placement

```cpp
#include <igl/exact_geodesic.h>

Eigen::VectorXi VS, FS, VT, FT; // source/target vertex/face indices
Eigen::VectorXd d;               // output distances

igl::exact_geodesic(V, F, VS, FS, VT, FT, d);
```

libigl wraps **Danil Kirsanov's exact geodesic algorithm** (based on the MMP algorithm — Mitchell, Mount, Papadimitriou 1987). This computes **exact** geodesic distances on piecewise linear surfaces, not the approximate Dijkstra-on-graph approximation. The MMP algorithm maintains a wavefront of windows propagating across triangle edges — O(n² log n) worst case but fast in practice.

For seam placement, geodesic distances give the cost of a cut path between two vertices. The **minimum seam** problem becomes: find the minimum-weight spanning tree on the cut graph, where edge weights are geodesic distances penalized by visibility and feature alignment.

---

## IV. xAtlas: Industrial UV Packing

**xAtlas** (Jonathan Young, based on NVIDIA's nvAtlas) is a C library for automatic UV unwrapping and atlas packing, used in production tools including UE5's lightmap baker and several game engines.

### 4.1 Architecture

xAtlas operates in three phases:

**Phase 1: Chart generation** — the mesh is segmented into charts (UV islands) using a **region-growing algorithm** driven by a cost function:

```cpp
xatlas::Atlas *atlas = xatlas::Create();

xatlas::MeshDecl meshDecl;
meshDecl.vertexCount     = vertexCount;
meshDecl.vertexPositionData   = positions;
meshDecl.vertexPositionStride = sizeof(float) * 3;
meshDecl.vertexNormalData     = normals;
meshDecl.vertexNormalStride   = sizeof(float) * 3;
meshDecl.indexCount      = indexCount;
meshDecl.indexData       = indices;
xatlas::AddMesh(atlas, meshDecl);

xatlas::ChartOptions chartOptions;
chartOptions.maxChartArea     = 0.0f;   // no area limit
chartOptions.maxBoundaryLength = 0.0f;  // no boundary limit
chartOptions.normalDeviationWeight = 2.0f;  // penalize normal variation
chartOptions.roundnessWeight  = 0.01f;
chartOptions.straightnessWeight = 6.0f;  // prefer straight seams
chartOptions.normalSeamWeight = 4.0f;   // penalize cutting across normals
chartOptions.textureSeamWeight = 0.5f;
chartOptions.maxCost          = 2.0f;   // max distortion per chart
```

The cost function balances: normal deviation across the chart (large normal variation = more distortion in the parameterization), boundary straightness (jagged seams pack poorly), and existing hard seams in the mesh.

**Phase 2: Parameterization** — each chart is independently parameterized using a variant of LSCM. Charts are small connected patches, so the parameterization is well-conditioned and distortion is bounded.

**Phase 3: Packing** — charts are packed into the atlas using a **skyline bin-packing algorithm** with optional rotation:

```cpp
xatlas::PackOptions packOptions;
packOptions.padding       = 2;     // texel padding between charts
packOptions.texelsPerUnit = 32.0f; // desired texels per world unit
packOptions.resolution    = 1024;  // target atlas resolution
packOptions.bilinear      = true;  // leave room for bilinear sampling
packOptions.blockAlign    = true;  // align to 4×4 for BC compression

xatlas::Pack(atlas, packOptions);
xatlas::Generate(atlas, chartOptions, packOptions);
```

`texelsPerUnit` is the **texel density** parameter — the number of UV atlas pixels per unit of 3D world-space distance. Setting this uniformly ensures consistent sharpness across all surfaces regardless of their actual polygon density or UV island shape.

### 4.2 Output Structure and Remeshing

After generation, xAtlas provides a **new vertex buffer** — critically, xAtlas may need to duplicate vertices at UV seams (one vertex in 3D can appear in two different UV islands, requiring two UV-distinct vertices):

```cpp
const xatlas::Atlas *a = atlas;
for (uint32_t i = 0; i < a->meshCount; i++) {
    const xatlas::Mesh &mesh = a->meshes[i];

    // New vertices (may be > original count due to seam splitting)
    for (uint32_t v = 0; v < mesh.vertexCount; v++) {
        const xatlas::Vertex &vertex = mesh.vertexArray[v];
        newUVs[v]  = {vertex.uv[0] / a->width, vertex.uv[1] / a->height};
        newPos[v]  = originalPositions[vertex.xref];  // original vertex index
    }

    // New index buffer referencing new vertices
    for (uint32_t idx = 0; idx < mesh.indexCount; idx++) {
        newIndices[idx] = mesh.indexArray[idx];
    }
}
```

The `vertex.xref` field maps new vertices back to original vertices — essential for transferring non-UV vertex attributes (positions, normals, tangents, blend weights) to the new mesh.

---

## V. OpenImageIO (OIIO): The Production Image Pipeline

**OpenImageIO** (Larry Gritz, Sony Pictures Imageworks) is the industry standard library for image I/O in VFX and game production. It abstracts 100+ image formats behind a unified API and handles the color space management that makes correct texturing possible.

### 5.1 Reading Textures with Correct Color Management

```cpp
#include <OpenImageIO/imageio.h>
#include <OpenImageIO/imagebuf.h>
#include <OpenImageIO/imagebufalgo.h>

using namespace OIIO;

// Read an sRGB albedo texture
ImageBuf src("diffuse_albedo.png");
ImageSpec spec = src.spec();

// Convert from sRGB to linear (ACEScg or scene-linear)
ImageBuf linear;
ImageBufAlgo::colorconvert(linear, src,
    "sRGB",      // source color space
    "linear",    // destination color space
    true,        // unpremultiply alpha before conversion
    ColorConfig("path/to/ocio/config.ocio"));
```

**OCIO (OpenColorIO)** integration is critical here. OIIO delegates color space transformations to OCIO, which supports arbitrary LUT-based transforms (ACES workflow, DCI-P3 for display, etc.). The OCIO config file defines the full color pipeline — every texture read must declare its color space so downstream operations work in a consistent linear light space.

### 5.2 Mip Generation with Custom Filters

```cpp
ImageBuf mipped;
ImageBufAlgo::make_texture(
    ImageBufAlgo::MakeTxTexture,  // output type
    src,                           // source image
    "output.tx",                   // .tx = OIIO's optimized tiled format
    ImageSpec(),                   // extra spec overrides
    &std::cout                     // progress output
);
```

The `.tx` format is OIIO's **tiled, mip-mapped, compressed** texture format based on TIFF. Tiling (default 64×64) is critical for GPU cache performance — a GPU rendering a small screen-space footprint of the texture should fetch one or two tiles, not full scanlines. Without tiling, accessing a small mip level requires seeking through a full scanline-organized file.

**Custom mip filter**: The default mip downsampling uses a box filter (simple average). For production, use a **Lanczos** or **Blackman-Harris** kernel to reduce aliasing:

```cpp
ImageSpec mipSpec;
mipSpec.attribute("maketx:filtername", "lanczos3");
mipSpec.attribute("maketx:filterwidth", 3.0f);
mipSpec.attribute("maketx:sharpen", 0.0f);
mipSpec.attribute("maketx:ignore_unassigned", 1);
```

Lanczos3 (3-lobe sinc × Lanczos window) gives near-optimal anti-aliasing with controlled ringing. The Blackman-Harris window has slightly more frequency-domain roll-off, trading a touch of sharpness for less ringing at texture boundaries.

### 5.3 ImageBufAlgo for Texture Processing

OIIO's `ImageBufAlgo` namespace contains production-grade image processing kernels, all properly multithreaded via Intel TBB:

```cpp
// Generate normal map from height map
ImageBuf heightmap("displacement.exr");
ImageBuf normalmap;

// Sobel operator computes height gradients → normal directions
ImageBuf dx, dy;
ImageBufAlgo::sobel(dx, heightmap);  // ∂h/∂x
// Manual normal reconstruction:
// N = normalize((-dx, -dy, 1/bumpScale))

// Dilate UV islands to prevent seam bleeding
ImageBuf dilated;
ImageBufAlgo::dilate(dilated, albedo, 4);  // 4-pixel dilation kernel

// Channel packing (roughness + metallic + AO into RGB)
ImageBuf packed;
ImageBufAlgo::channel_append(packed, roughness, metallic);
ImageBufAlgo::channel_append(packed, packed, ao);
```

**Channel packing** is a standard production optimization — combining roughness (R), metallic (G), and AO (B) channels into a single RGB texture reduces texture sampler slots and GPU memory bandwidth relative to three separate single-channel textures (Epic Games, _Unreal Engine Materials: Texture Packing_; Khronos glTF 2.0 specification §5.22.1). The shader unpacks them as `packed.r`, `packed.g`, `packed.b`.

---

## VI. MaterialX: Vendor-Neutral Material Specification

**MaterialX** (Lucasfilm/ILM, now ASWF project) is a graph-based material specification standard — the equivalent of USD for materials. It defines a node graph in XML that is **renderer-agnostic** and can be compiled to GLSL, HLSL, OSL, or MDL.

### 6.1 Material Graph Structure

```xml
<?xml version="1.0"?>
<materialx version="1.38">

  <!-- Standard PBR surface shader -->
  <standard_surface name="chrome_material" type="surfaceshader">
    <input name="base" type="float" value="1.0"/>
    <input name="base_color" type="color3" nodename="albedo_tex"/>
    <input name="specular_roughness" type="float" nodename="rough_channel"/>
    <input name="metalness" type="float" nodename="metal_channel"/>
    <input name="normal" type="vector3" nodename="normal_map_node"/>
  </standard_surface>

  <!-- Texture nodes -->
  <tiledimage name="albedo_tex" type="color3">
    <input name="file" type="filename" value="albedo.png"/>
    <input name="default" type="color3" value="0.18, 0.18, 0.18"/>
    <input name="uvtiling" type="vector2" value="2.0, 2.0"/>
  </tiledimage>

  <!-- Normal map decode node (tangent-space decode built-in) -->
  <normalmap name="normal_map_node" type="vector3">
    <input name="in" type="vector3" nodename="normal_tex"/>
    <input name="space" type="string" value="tangent"/>
  </normalmap>

</materialx>
```

The `<normalmap>` node is semantically significant — it encodes the knowledge that this texture needs TBN-space decoding, not just raw sampling. MaterialX's node library includes physically meaningful nodes like `<dielectricbsdf>`, `<subsurface_bsdf>`, `<sheen_bsdf>` that map directly to BRDF components, enabling physically correct material composition at the graph level.

### 6.2 Code Generation

MaterialX's code generation framework (`MaterialXGenShader`) compiles node graphs to target GLSL/HLSL:

```cpp
#include <MaterialXGenShader/Shader.h>
#include <MaterialXGenGlsl/GlslShaderGenerator.h>

mx::DocumentPtr doc = mx::createDocument();
mx::readFromXmlFile(doc, "material.mtlx");

mx::GenContext context(mx::GlslShaderGenerator::create());
context.getOptions().targetColorSpaceOverride = "lin_rec709";
context.getOptions().fileTextureVerticalFlip   = true;

mx::ShaderPtr shader = context.getShaderGenerator().generate(
    "chrome_material",
    doc->getNodeDef("ND_standard_surface_surfaceshader"),
    context);

std::string vertexSource   = shader->getSourceCode(mx::Stage::VERTEX);
std::string fragmentSource = shader->getSourceCode(mx::Stage::PIXEL);
```

The generated GLSL includes the full PBR BRDF implementation, texture sampling with correct color space transforms, normal map decoding, and all the boilerplate. The shader generator handles all target differences — Vulkan GLSL vs. OpenGL GLSL vs. WebGL — from a single node graph definition.

---

## VII. Three.js: WebGL Texturing Architecture

Three.js abstracts WebGL's texture API into a class hierarchy worth understanding at the source level.

### 7.1 Texture Object Internals

```javascript
import * as THREE from "three";
import { EXRLoader } from "three/examples/jsm/loaders/EXRLoader.js";
import { RGBELoader } from "three/examples/jsm/loaders/RGBELoader.js";

// Standard sRGB texture
const loader = new THREE.TextureLoader();
const albedo = await loader.loadAsync("albedo.png");
albedo.colorSpace = THREE.SRGBColorSpace; // THREE.js 0.152+
albedo.wrapS = THREE.RepeatWrapping;
albedo.wrapT = THREE.RepeatWrapping;
albedo.repeat.set(2, 2);
albedo.anisotropy = renderer.capabilities.getMaxAnisotropy(); // hardware max
albedo.generateMipmaps = true;
albedo.minFilter = THREE.LinearMipmapLinearFilter; // trilinear

// HDR environment map (EXR)
const exrLoader = new EXRLoader();
const envMap = await exrLoader.loadAsync("env.exr");
envMap.mapping = THREE.EquirectangularReflectionMapping;
scene.environment = envMap; // IBL source for all MeshStandardMaterial
```

**`colorSpace = THREE.SRGBColorSpace`** is the Three.js equivalent of OpenGL's `GL_SRGB8_ALPHA8` — it instructs the WebGL backend to declare the texture with the sRGB internal format, enabling hardware-accelerated linearization on sample. Without this, albedo textures are interpreted as linear, causing visually incorrect (too dark in shadows, too bright in highlights) BRDF results.

### 7.2 MeshStandardMaterial as a PBR Implementation

`MeshStandardMaterial` implements the **GGX microfacet BRDF** with:

```javascript
const material = new THREE.MeshStandardMaterial({
  map: albedo, // base color (sRGB)
  normalMap: normalTex, // tangent-space normals
  normalScale: new THREE.Vector2(1, 1), // normal intensity
  roughnessMap: ormTex, // R channel
  metalnessMap: ormTex, // B channel (ORM packing)
  roughness: 1.0, // multiplied with roughnessMap
  metalness: 1.0, // multiplied with metalnessMap
  aoMap: ormTex, // R channel (AO)
  aoMapIntensity: 1.0,
  displacementMap: heightTex,
  displacementScale: 0.05, // world-space amplitude
  emissiveMap: emissiveTex,
  emissive: new THREE.Color(1, 1, 1),
  emissiveIntensity: 2.0, // HDR multiplier
  envMapIntensity: 1.0, // IBL contribution scale
});
```

The `roughnessMap` and `metalnessMap` pointing to the same ORM texture is **channel packing** — Three.js internally samples:

- `roughnessMap.g` for roughness (green channel)
- `metalnessMap.b` for metalness (blue channel)
- `aoMap.r` for ambient occlusion (red channel)

This is encoded in the Three.js GLSL chunk `roughnessmap_fragment.glsl.js` — reading the library source reveals the exact channel conventions, which are not always documented.

### 7.3 Custom ShaderMaterial and GLSL Chunks

Three.js's shader system uses **#include directives** to compose shader programs from reusable chunks. This is how you extend the PBR pipeline without rewriting the entire BRDF:

```javascript
const customMaterial = new THREE.ShaderMaterial({
  uniforms: {
    ...THREE.UniformsLib.lights, // inject light uniforms
    ...THREE.UniformsLib.fog,
    uAlbedo: { value: albedo },
    uNormalMap: { value: normalTex },
    uRoughness: { value: 0.5 },
    uTime: { value: 0.0 },
  },

  vertexShader: `
        #include <common>
        #include <uv_pars_vertex>
        #include <normal_pars_vertex>
        #include <shadowmap_pars_vertex>
        
        void main() {
            #include <uv_vertex>
            #include <beginnormal_vertex>
            #include <defaultnormal_vertex>
            #include <begin_vertex>
            #include <project_vertex>
            #include <shadowmap_vertex>
        }
    `,

  fragmentShader: `
        #include <common>
        #include <packing>
        #include <uv_pars_fragment>
        #include <normal_pars_fragment>
        #include <lights_pars_begin>
        #include <lights_physical_pars_fragment>  // full PBR BRDF
        
        uniform sampler2D uAlbedo;
        uniform float uTime;
        
        void main() {
            PhysicalMaterial material;
            material.diffuseColor  = texture2D(uAlbedo, vUv).rgb;
            material.roughness     = 0.5;
            material.specularColor = vec3(0.04); // dielectric F0
            
            // Custom procedural detail layered on top
            float noise = fract(sin(dot(vUv, vec2(127.1, 311.7))) * 43758.5453);
            material.roughness += noise * 0.1;
            
            #include <lights_fragment_begin>
            #include <lights_fragment_maps>
            #include <lights_fragment_end>
            
            gl_FragColor = vec4(outgoingLight, 1.0);
        }
    `,
  lights: true,
});
```

This pattern lets you inject custom logic (procedural noise, animated UV, custom blending) into the standard PBR lighting pipeline without reimplementing the entire Cook-Torrance BRDF.

---

## VIII. Filament: Mobile-Grade PBR Library

**Filament** (Google) is an open-source physically based rendering engine designed for high performance on Android and iOS, with a rigorous mathematical basis documented in its published PBR white paper.

### 8.1 Material System Architecture

Filament's `.filamat` compiled material format is generated from a high-level **material definition** (.mat file) via the `matc` compiler:

```glsl
// myMaterial.mat
material {
    name : "AdvancedPBR",
    shadingModel : lit,       // full PBR
    blending : opaque,

    parameters : [
        { type : sampler2d, name : albedoMap },
        { type : sampler2d, name : normalMap },
        { type : sampler2d, name : ormMap },
        { type : float,     name : normalStrength },
        { type : float2,    name : uvScale },
    ],
}

fragment {
    void material(inout MaterialInputs m) {
        // UV with tiling
        float2 uv = getUV0() * materialParams.uvScale;

        // Albedo (sRGB automatically linearized)
        m.baseColor = texture(materialParams_albedoMap, uv);

        // ORM texture: R=AO, G=Roughness, B=Metallic
        float3 orm = texture(materialParams_ormMap, uv).rgb;
        m.ambientOcclusion = orm.r;
        m.roughness        = orm.g;
        m.metallic         = orm.b;

        // Tangent-space normal with adjustable strength
        float3 n = texture(materialParams_normalMap, uv).rgb * 2.0 - 1.0;
        n.xy *= materialParams.normalStrength;
        m.normal = normalize(n);
    }
}
```

The `matc` compiler performs **static analysis** on this code — it determines exactly which V-Buffer inputs (UV sets, tangents, vertex colors) are needed and generates a minimal vertex shader variant, eliminating unused interpolants. This is critical for mobile GPU performance.

### 8.2 Filament's BRDF Deviations from Standard Cook-Torrance

Filament's PBR white paper documents several important deviations from the standard microfacet model that are worth knowing at a PhD level:

**Energy conservation normalization**: Standard GGX is not energy-conserving — a rough mirror appears darker than a smooth one even when they should have equal albedo. Filament applies the **DFG normalization** from Karis (Epic, 2013): divide the specular term by the pre-integrated **DFG lookup table** sampled at (NdotV, roughness). This ensures total outgoing energy ≤ incoming energy.

**Multi-scattering correction**: Single-scattering microfacet models lose energy due to inter-facet occlusion — photons that bounce between microfacets are not accounted for. Filament uses the **Kelemen-Szirmay-Kalos** multi-scatter term to recover this lost energy, especially important for high-roughness metals.

**Clear coat layer**: Filament supports a full two-layer BRDF (base material + clear coat) where the clear coat attenuates light reaching the base layer by the Fresnel factor of the coating, and the base material's IBL contribution is modulated accordingly.

---

## IX. USD and Hydra: The Scene-Level Texture Pipeline

**USD (Universal Scene Description)** and its rendering interface **Hydra** represent the highest architectural level — how textures flow through a complete production pipeline.

### 9.1 USD Material Binding

```python
from pxr import Usd, UsdGeom, UsdShade, Sdf

stage = Usd.Stage.CreateNew("scene.usda")

# Create a mesh
mesh = UsdGeom.Mesh.Define(stage, "/World/Cube")

# Create a MaterialX-based material in USD
material = UsdShade.Material.Define(stage, "/World/Materials/Chrome")

# Bind MaterialX document as a USD material
mx_shader = UsdShade.Shader.Define(stage, "/World/Materials/Chrome/Shader")
mx_shader.CreateIdAttr("ND_standard_surface_surfaceshader")

# Set PBR parameters
mx_shader.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set((0.8, 0.8, 0.8))
mx_shader.CreateInput("specular_roughness", Sdf.ValueTypeNames.Float).Set(0.2)
mx_shader.CreateInput("metalness", Sdf.ValueTypeNames.Float).Set(1.0)

# Connect to material output
material.CreateSurfaceOutput().ConnectToSource(
    mx_shader.ConnectableAPI(), "surface"
)

# Bind material to mesh
UsdShade.MaterialBindingAPI(mesh).Bind(material)
```

### 9.2 Hydra's Render Delegate Architecture

Hydra is a **scene graph hydration framework** — it translates a USD scene into renderer-specific data. The key insight is that **textures are resolved lazily**: the `HdTextureHandle` returned by `HdResourceRegistry::AllocateTextureHandle` is a proxy — the actual GPU upload happens when the renderer's delegate calls `HdTextureObject::Load()` during the first draw that requires that texture.

The **texture cache key** is the `HdTextureIdentifier` — a struct combining the file path, sub-texture index, and a `HdSubtextureIdentifier` that encodes sampling parameters. This key-based caching ensures that the same texture file used by 1000 mesh instances results in exactly one GPU upload.

**Texture LOD budget management** in Hydra: Production scenes have texture budgets exceeding GPU VRAM. Hydra's `HdTextureUtils::LoadTexture` supports tiled sparse textures (equivalent to DX12's reserved resources) — only the resident mip levels are backed by physical VRAM, and a page fault handler streams in tiles as needed. This is the architecture behind game-engine **virtual texturing** (Megatexture, id's Virtual Texture).

---

## X. The Full PhD-Level Stack in Code

Here is what a complete, research-grade texture pipeline looks like when these libraries compose together:

```
USD Stage
  └── Material (MaterialX graph in USD)
        ├── Albedo.tx      (OIIO tiled EXR, linearized by OCIO)
        ├── ORM.tx         (channel-packed, BC7 compressed)
        ├── Normal.tx      (BC5, tangent-space, 16-bit)
        └── Displacement.exr (16-bit half-float, for tessellation)

Mesh UV Layout
  ├── xAtlas  → chart segmentation, LSCM per-chart parameterization
  ├── libigl  → ARAP refinement, geodesic seam optimization
  └── OIIO    → bake ray-cast results into .tx with correct mip chain

Render Path
  ├── Hydra delegate → resolves USD material, populates Vulkan descriptors
  ├── MaterialX codegen → compiles to SPIR-V via glslang
  └── Filament/custom BRDF → GGX + multi-scatter + energy conservation
```

Every layer in this stack is mathematically grounded: LSCM minimizes a conformal energy functional, Vulkan barriers enforce memory coherency, OCIO transforms enforce color space correctness, and the Cook-Torrance BRDF conserves energy. The PhD contribution sits in understanding exactly which assumptions each layer makes — and what breaks when they're violated.
