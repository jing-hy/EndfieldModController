/*=============================================================================
                                                           
 d8b 888b     d888 888b     d888 8888888888 8888888b.   .d8888b.  8888888888 
 Y8P 8888b   d8888 8888b   d8888 888        888   Y88b d88P  Y88b 888        
     88888b.d88888 88888b.d88888 888        888    888 Y88b.      888        
 888 888Y88888P888 888Y88888P888 8888888    888   d88P  "Y888b.   8888888    
 888 888 Y888P 888 888 Y888P 888 888        8888888P"      "Y88b. 888        
 888 888  Y8P  888 888  Y8P  888 888        888 T88b         "888 888        
 888 888   "   888 888   "   888 888        888  T88b  Y88b  d88P 888        
 888 888       888 888       888 8888888888 888   T88b  "Y8888P"  8888888888                                                                 
                                                                            
    Copyright (c) Pascal Gilcher. All rights reserved.
    
    * Unauthorized copying of this file, via any medium is strictly prohibited
 	* Proprietary and confidential

 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 DEALINGS IN THE SOFTWARE.

===============================================================================

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/

/*=============================================================================
	Preprocessor settings
=============================================================================*/

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform int SPECULAR_GI_Q <
	ui_type = "combo";
    ui_label = "Quality";
	ui_items = "Low\0Medium\0High\0Ultra\0";
    ui_category = "Ray Tracing";
> = 1;

uniform float RT_Z_THICKNESS <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
    ui_label = "Object Thickness";
    ui_tooltip = "The shader does not know how much objects extend beyond the visible side\nand has to assume a fixed value.\n\nSet this value as low as possible without losing GI intensity.";
	ui_category = "Ray Tracing";
> = 0.25;

uniform float RT_ROUGHNESS <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 0.5;
    ui_label = "Surface Roughness";
	ui_tooltip = "BRDF surface roughness determines how glossy/matte the specular GI becomes.\nLower values result in more glossy reflections, higher values in more diffuse reflections.";
    ui_category = "Ray Tracing";
> = 0.2;

uniform float RT_FRESNEL_F0 <
	ui_type = "drag";
	ui_min = 0.04; ui_max = 0.5;
    ui_label = "Fresnel F0";
	ui_tooltip = "Intensity of reflections at normal incidence.\0Higher values cause stronger reflections when looking at surfaces head-on.\0Physically accurate for most materials is 0.04 - 0.2";
    ui_category = "Ray Tracing";
> = 0.04;

#define GGX_ALPHA max(0.001, RT_ROUGHNESS * RT_ROUGHNESS)

uniform float RT_FADE_DEPTH <
	ui_type = "drag";
    ui_label = "Fade-Out Range";
	ui_min = 0.001; ui_max = 1.0;
	ui_tooltip = "Distance falloff, higher values increase RTGI draw distance.";
    ui_category = "Blending";
> = 0.3;

uniform int RT_DEBUG_VIEW <
	ui_type = "combo";
    ui_label = "Debug View";
	ui_items = "Disabled\0Specular RTGI\0Validation Layer\0";
	ui_tooltip = "Validation Layer:\n\n- Depth\n- Lighting\n- Normal Vectors\n- Optical Flow";
    ui_category = "Debug";
> = 0;
/*
uniform float4 tempF1 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF2 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF3 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF4 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF5 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF6 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform float4 tempF7 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
> = float4(1,1,1,1);

uniform bool debug_key_down < source = "key"; keycode = 0x46; mode = ""; >;//f
uniform bool debug_key_down2 < source = "key"; keycode = 0x47; mode = ""; >;//g
uniform bool debug_key_down3 < source = "key"; keycode = 0x48; mode = ""; >;//h
*/
/*=============================================================================
	Textures, Samplers, Globals, Structs
=============================================================================*/

//do NOT change anything here. "hurr durr I changed this and now it works"
//you ARE breaking things down the line, if the shader does not work without changes
//here, it's by design.

uniform uint  FRAMECOUNT  < source = "framecount"; >;
uniform float FRAMETIME   < source = "frametime";  >;

#define VARIANCE_FP16_QUANTIZATION_SCALE 128.0

texture ColorInputTex : COLOR;
texture DepthInputTex : DEPTH;
sampler ColorInput 	{ Texture = ColorInputTex; };
sampler DepthInput  { Texture = DepthInputTex; MinFilter = POINT; MipFilter = POINT; MagFilter = POINT;};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_depth.fxh"
#include ".\MartysMods\mmx_math.fxh"
#include ".\MartysMods\mmx_qmc.fxh"
#include ".\MartysMods\mmx_bxdf.fxh"
#include ".\MartysMods\mmx_deferred.fxh"
#include ".\MartysMods\mmx_camera.fxh"
#include ".\MartysMods\mmx_debug.fxh"
#include ".\MartysMods\mmx_texture.fxh"
#include ".\MartysMods\mmx_hash.fxh"
#include ".\MartysMods\mmx_sfc.fxh"
#include ".\MartysMods\mmx_harmonics.fxh"

#define MIN_MAG_MIP_POINT  MinFilter = POINT; MipFilter = POINT; MagFilter = POINT;

//blue noise seeds, offline LUTs
texture SPECGI_STBN128     < source = "iMMERSE_bluenoise_temporal128.png"; >   { Width = 1024; Height = 512; Format = RGBA8; };
sampler	sSPECGI_STBN128    { Texture = SPECGI_STBN128; };
texture SPECGI_STBN128_s   < source = "iMMERSE_bluenoise_temporal128_s.png"; > { Width = 1024; Height = 512; Format = RGBA8; };
sampler	sSPECGI_STBN128_s  { Texture = SPECGI_STBN128_s; };

texture SPECGI_GGXIntegralLUT  < source = "iMMERSE_ggxint.png"; > { Width = 32; Height = 32; Format = R8; };
sampler	sSPECGI_GGXIntegralLUT { Texture = SPECGI_GGXIntegralLUT;  };

//GI inputs
texture SPECGI_QuadTree     { Width = BUFFER_WIDTH_DLSS + 128; Height = BUFFER_HEIGHT_DLSS + 128; Format = RG32F; MipLevels = 8;};
sampler sSPECGI_QuadTree	{ Texture = SPECGI_QuadTree;              MinFilter = POINT; MipFilter = POINT; MagFilter = POINT; };
storage stSPECGI_QuadTree0	{ Texture = SPECGI_QuadTree;  MipLevel = 0;};
storage stSPECGI_QuadTree1	{ Texture = SPECGI_QuadTree;  MipLevel = 1;};
storage stSPECGI_QuadTree2	{ Texture = SPECGI_QuadTree;  MipLevel = 2;};
storage stSPECGI_QuadTree3	{ Texture = SPECGI_QuadTree;  MipLevel = 3;};
storage stSPECGI_QuadTree4	{ Texture = SPECGI_QuadTree;  MipLevel = 4;};
storage stSPECGI_QuadTree5	{ Texture = SPECGI_QuadTree;  MipLevel = 5;};
storage stSPECGI_QuadTree6	{ Texture = SPECGI_QuadTree;  MipLevel = 6;};
storage stSPECGI_QuadTree7	{ Texture = SPECGI_QuadTree;  MipLevel = 7;};

//Working buffers
texture SPECGI_Aux0   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture SPECGI_Aux1   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture SPECGI_Aux2   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture SPECGI_Aux3   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture SPECGI_Aux4   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sSPECGI_Aux0	 { Texture = SPECGI_Aux0; };
sampler sSPECGI_Aux1	 { Texture = SPECGI_Aux1; };
sampler sSPECGI_Aux2	 { Texture = SPECGI_Aux2; };
sampler sSPECGI_Aux3	 { Texture = SPECGI_Aux3; };
sampler sSPECGI_Aux4	 { Texture = SPECGI_Aux4; };
storage stSPECGI_Aux0 { Texture = SPECGI_Aux0; };
storage stSPECGI_Aux1 { Texture = SPECGI_Aux1; };
storage stSPECGI_Aux2 { Texture = SPECGI_Aux2; };
storage stSPECGI_Aux3 { Texture = SPECGI_Aux3; };
storage stSPECGI_Aux4 { Texture = SPECGI_Aux4; };

texture SPECGI_PrevNormals   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RG16; };
sampler sSPECGI_PrevNormals	 { Texture = SPECGI_PrevNormals; };
storage stSPECGI_PrevNormals { Texture = SPECGI_PrevNormals; };

texture SPECGI_Accum  { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sSPECGI_Accum { Texture = SPECGI_Accum; };
storage stSPECGI_Accum { Texture = SPECGI_Accum; };

texture SPECGI_PrevTemporalHints  { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sSPECGI_PrevTemporalHints { Texture = SPECGI_PrevTemporalHints; };
storage stSPECGI_PrevTemporalHints { Texture = SPECGI_PrevTemporalHints; };

texture SPECGI_HitVectors   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F;MipLevels = 5; };
sampler sSPECGI_HitVectors	 { Texture = SPECGI_HitVectors; };
storage stSPECGI_HitVectors { Texture = SPECGI_HitVectors; };

texture SPECGI_Radiance   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA8; MipLevels = 8; };
sampler sSPECGI_Radiance  { Texture = SPECGI_Radiance; };
sampler sSPECGI_RadianceAnisotropic  { Texture = SPECGI_Radiance; MagFilter = ANISOTROPIC;MinFilter = ANISOTROPIC;MipFilter = ANISOTROPIC;};

storage stSPECGI_Radiance0	{ Texture = SPECGI_Radiance;  MipLevel = 0;};
storage stSPECGI_Radiance1	{ Texture = SPECGI_Radiance;  MipLevel = 1;};
storage stSPECGI_Radiance2	{ Texture = SPECGI_Radiance;  MipLevel = 2;};
storage stSPECGI_Radiance3	{ Texture = SPECGI_Radiance;  MipLevel = 3;};
storage stSPECGI_Radiance4	{ Texture = SPECGI_Radiance;  MipLevel = 4;};
storage stSPECGI_Radiance5	{ Texture = SPECGI_Radiance;  MipLevel = 5;};
storage stSPECGI_Radiance6	{ Texture = SPECGI_Radiance;  MipLevel = 6;};
storage stSPECGI_Radiance7	{ Texture = SPECGI_Radiance;  MipLevel = 7;};

struct VSOUT
{
    float4 vpos : SV_Position;
    float2 uv   : TEXCOORD0;
};

struct CSIN 
{
    uint3 groupthreadid     : SV_GroupThreadID;         
    uint3 groupid           : SV_GroupID;            
    uint3 dispatchthreadid  : SV_DispatchThreadID;     
    uint threadid           : SV_GroupIndex;
};

/*=============================================================================
	Functions
=============================================================================*/

float get_brdf(float ndotv, float alpha)
{
    float brdf = tex2Dlod(sSPECGI_GGXIntegralLUT, float2(ndotv, alpha), 0).x;
    return brdf * brdf; //stored sqrt
}

float2 pixel_idx_to_uv(uint2 pos, float2 texture_size)
{
    float2 inv_texture_size = rcp(texture_size);
    return pos * inv_texture_size + 0.5 * inv_texture_size;
}

bool check_boundaries(uint2 pos, uint2 dest_size)
{
    return all(pos < dest_size) && all(pos >= uint2(0, 0));
}

float3 srgb_to_AgX(float3 srgb)
{
    const float3x3 toagx = float3x3(0.842479, 0.0784336, 0.0792237, 
                                    0.042328, 0.8784686, 0.0791661, 
                                    0.042376, 0.0784336, 0.8791430);
    return mul(toagx, srgb);         
}

float3 AgX_to_srgb(float3 AgX)
{   
    const float3x3 fromagx = float3x3(1.19688,  -0.0980209, -0.0990297,
                                     -0.0528969, 1.1519,    -0.0989612,
                                     -0.0529716, -0.0980435, 1.15107);
    return mul(fromagx, AgX);            
}

float3 unpack_hdr(float3 color)
{
    color  = saturate(color);   
    color = color*0.283799*((2.52405+color)*color);    
    color = srgb_to_AgX(color);
    color = color * rcp(1.04 - saturate(color));    
    return color;
}

float3 pack_hdr(float3 color)
{
    color =  1.04 * color * rcp(color + 1.0);   
    color = AgX_to_srgb(color);    
    color  = saturate(color);
    color = 1.14374*(-0.126893*color+sqrt(color));
    return color;     
}

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    return o;
}

float hyperbolize_depth(float z)
{
    float f = RESHADE_DEPTH_LINEARIZATION_FAR_PLANE;
    return f * (z * rcp(1 + z * (f - 1)));
}

float linearize_depth(float x)
{
    x /= RESHADE_DEPTH_LINEARIZATION_FAR_PLANE - x * (RESHADE_DEPTH_LINEARIZATION_FAR_PLANE - 1.0); 
    return x;
}

float truez_to_device_z(float z)
{
    return hyperbolize_depth(Camera::z_to_depth(z));
}

float device_z_to_truez(float z)
{
    return Camera::depth_to_z(linearize_depth(z));
}

float3 proj_to_clip(float3 p)
{
    return float3(Camera::proj_to_uv(p), hyperbolize_depth(Camera::z_to_depth(p.z)));
}

float3 clip_to_proj(float3 p)
{
    return Camera::uv_to_proj(p.xy, Camera::depth_to_z(linearize_depth(p.z)));
}

float sg_overlap(float3 eta1, float3 eta2, float alpha1, float alpha2, float beta)
{
    float a1a1 = alpha1*alpha1;
    float a2a2 = alpha2*alpha2;    
    float v = 2.0 / (a1a1 + a2a2);
    float templog = 4.0 / (2 + a1a1/a2a2 + a2a2/a1a1);    
    return exp(beta * (0.5 * log(templog) + v * dot(eta1, eta2) - v));
}

float get_fade_factor(float depth)
{   
    if(RT_DEBUG_VIEW) return 1;

    float fade = saturate(1 - depth * depth); //fixed fade that smoothly goes to 0 at depth = 1, to multiply on top 
    float t = depth / (1e-6 + RT_FADE_DEPTH * RT_FADE_DEPTH);
    return saturate(exp2(-t) * fade - 0.01); //so it actually reaches 0    
}

float3 showmotion(float2 motion)
{
	float angle = atan2(motion.y, motion.x);
	float dist = length(motion);
	float3 rgb = saturate(3 * abs(2 * frac(angle / 6.283 + float3(0, -1.0/3.0, 1.0/3.0)) - 1) - 1);
	return lerp(0.5, rgb, saturate(log(1 + dist * 400.0 / FRAMETIME)));//normalize by frametime such that we don't need to adjust visualization intensity all the time
}

/*=============================================================================
	Downsample Depth
=============================================================================*/

float2 transform_to_storage(float2 minmax_z)
{
    minmax_z = abs(minmax_z); //flip sign since we did min() for both min and max
    float thickness = RT_Z_THICKNESS * RT_Z_THICKNESS * minmax_z.y;//RT_Z_THICKNESS * RT_Z_THICKNESS * (1 + minmax_z.x * 0.01);
    minmax_z.y = Camera::z_to_depth(minmax_z.y + thickness);        
    minmax_z.y = hyperbolize_depth(minmax_z.y);
    minmax_z.x = Camera::z_to_depth(minmax_z.x);
    minmax_z.x = hyperbolize_depth(minmax_z.x);
    return minmax_z;   
}

groupshared float2 z_tgsm[32*32];

void SpecularHiZDownsampleCS(in CSIN i)
{
    uint2 p = i.groupid.xy * 32u + SFC::morton_i_to_xy(i.threadid);
    
    uint2  quad_pos[4];
    float2 quad_uv[4];
    float4 quad_z[4];
    quad_pos[0] = p * 2 + uint2(0, 0);
    quad_pos[1] = p * 2 + uint2(1, 0);
    quad_pos[2] = p * 2 + uint2(0, 1);
    quad_pos[3] = p * 2 + uint2(1, 1);    
    quad_uv[0] = Depth::correct_uv(saturate((quad_pos[0] * 2 + 1) * BUFFER_PIXEL_SIZE_DLSS));
    quad_uv[1] = Depth::correct_uv(saturate((quad_pos[1] * 2 + 1) * BUFFER_PIXEL_SIZE_DLSS));
    quad_uv[2] = Depth::correct_uv(saturate((quad_pos[2] * 2 + 1) * BUFFER_PIXEL_SIZE_DLSS));
    quad_uv[3] = Depth::correct_uv(saturate((quad_pos[3] * 2 + 1) * BUFFER_PIXEL_SIZE_DLSS));    
#if RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN      // Flip vertically for gather order
    quad_z[0] = tex2DgatherR(DepthInput, quad_uv[0]).wzyx; 
    quad_z[1] = tex2DgatherR(DepthInput, quad_uv[1]).wzyx; 
    quad_z[2] = tex2DgatherR(DepthInput, quad_uv[2]).wzyx; 
    quad_z[3] = tex2DgatherR(DepthInput, quad_uv[3]).wzyx; 
#else 
    quad_z[0] = tex2DgatherR(DepthInput, quad_uv[0]); 
    quad_z[1] = tex2DgatherR(DepthInput, quad_uv[1]); 
    quad_z[2] = tex2DgatherR(DepthInput, quad_uv[2]); 
    quad_z[3] = tex2DgatherR(DepthInput, quad_uv[3]); 
#endif

    float2 aabb = 1e10;

    [unroll]
    for(int j = 0; j < 4; ++j)
    {
        quad_z[j] = Depth::linearize(quad_z[j]);
        quad_z[j].w = Camera::depth_to_z(quad_z[j].w); 
        quad_z[j].x = Camera::depth_to_z(quad_z[j].x);   
        quad_z[j].z = Camera::depth_to_z(quad_z[j].z); 
        quad_z[j].y = Camera::depth_to_z(quad_z[j].y);  
        tex2Dstore(stSPECGI_QuadTree0, quad_pos[j] * 2 + uint2(0, 0), transform_to_storage(quad_z[j].ww).xyyy);        
        tex2Dstore(stSPECGI_QuadTree0, quad_pos[j] * 2 + uint2(0, 1), transform_to_storage(quad_z[j].xx).xyyy);       
        tex2Dstore(stSPECGI_QuadTree0, quad_pos[j] * 2 + uint2(1, 0), transform_to_storage(quad_z[j].zz).xyyy);        
        tex2Dstore(stSPECGI_QuadTree0, quad_pos[j] * 2 + uint2(1, 1), transform_to_storage(quad_z[j].yy).xyyy);
        float2 quad_aabb = float2(minc(quad_z[j]), maxc(quad_z[j]));
        tex2Dstore(stSPECGI_QuadTree1, quad_pos[j], transform_to_storage(quad_aabb).xyxy);
        aabb = min(aabb, float2(quad_aabb.x, -quad_aabb.y));
    }

    tex2Dstore(stSPECGI_QuadTree2, p, transform_to_storage(aabb).xyxy);
    z_tgsm[i.threadid] = aabb;
    barrier();

    [unroll]
    for(uint stride = 1; stride < 1024; barrier())
    {
        p >>= 1;
        uint next_stride = stride * 4;
        [branch]
        if(i.threadid % next_stride == 0)
        {
            aabb = min(aabb, z_tgsm[i.threadid + stride    ]);
            aabb = min(aabb, z_tgsm[i.threadid + stride * 2]);  
            aabb = min(aabb, z_tgsm[i.threadid + stride * 3]);            
            if(stride ==   1) tex2Dstore(stSPECGI_QuadTree3, p, transform_to_storage(aabb).xyxy);
            if(stride ==   4) tex2Dstore(stSPECGI_QuadTree4, p, transform_to_storage(aabb).xyxy);
            if(stride ==  16) tex2Dstore(stSPECGI_QuadTree5, p, transform_to_storage(aabb).xyxy);
            if(stride ==  64) tex2Dstore(stSPECGI_QuadTree6, p, transform_to_storage(aabb).xyxy);
            if(stride == 256) tex2Dstore(stSPECGI_QuadTree7, p, transform_to_storage(aabb).xyxy);
            z_tgsm[i.threadid] = aabb;
        }
        stride = next_stride;
    }
}

/*=============================================================================
	Downsample Radiance
=============================================================================*/

float4 rgb_to_logluv(float3 rgb)
{
    float3x3 m = float3x3(0.2209, 0.3390, 0.4184,
                          0.1138, 0.6780, 0.7319,
                          0.0102, 0.1130, 0.2969);
    float3 Xp_Y_XYZp = max(mul(rgb, m), 1e-6);
    float Le = 2 * log2(Xp_Y_XYZp.y) + 127;
    return float4(Xp_Y_XYZp.xy / Xp_Y_XYZp.z, floor(Le) / 255.0, frac(Le));
}

float3 logluv_to_rgb(float4 logluv)
{
    float3x3 m = float3x3(6.0013, -2.700, -1.7995,
                          -1.332, 3.1029, -5.7720,
                          0.3007, -1.088,  5.6268);
    float3 res;
    res.y = exp2((logluv.z * 255 + logluv.w) * 0.5 - 63.5);
    res.z = res.y / logluv.y;
    res.x = res.z * logluv.x;
    return max(mul(res, m), 0);
}

 
void RadianceMiptreePS(in VSOUT i, out float4 o : SV_Target0)
{
    o = tex2D(ColorInput, i.uv);
    o.rgb = unpack_hdr(o.rgb);   
    o = rgb_to_logluv(o.rgb);    
}

static const float2 downsample_offsets[24] = 
{
                                                    float2(-0.5, -2.5),     float2(0.5, -2.5),                                              
                            float2(-1.5, -1.5),     float2(-0.5, -1.5),     float2(0.5, -1.5), float2(-1.5, -1.5),                       
    float2(-2.5, -0.5),     float2(-1.5, -0.5),     float2(-0.5, -0.5),     float2(0.5, -0.5), float2(-1.5, -0.5), float2(2.5, -0.5),
    float2(-2.5,  0.5),     float2(-1.5,  0.5),     float2(-0.5,  0.5),     float2(0.5,  0.5), float2(-1.5,  0.5), float2(2.5,  0.5),
                            float2(-1.5,  1.5),     float2(-0.5,  1.5),     float2(0.5,  1.5), float2(-1.5,  1.5),                       
                                                    float2(-0.5,  2.5),     float2(0.5,  2.5)                                             
};
//no storages as function arguments makes copypaste go brr.
//I hate everything about this but it's necessary :/
void DownsampleRadianceCS0(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance0);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance1);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance0, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance1, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS1(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance1);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance2);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance1, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance2, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS2(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance2);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance3);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance2, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance3, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS3(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance3);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance4);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance3, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance4, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS4(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance4);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance5);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance4, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance5, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS5(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance5);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance6);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance5, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance6, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}
void DownsampleRadianceCS6(in CSIN i)
{
    float2 src_size = tex2Dsize(stSPECGI_Radiance6);
    float2 dst_size = tex2Dsize(stSPECGI_Radiance7);
    float2 uv = (i.dispatchthreadid.xy + 0.5) / dst_size;

    float4 logsum = 0;
    [unroll]for(int j = 0; j < 24; ++j)
    {
        float2 tap_uv = uv + downsample_offsets[j] / src_size;              
        float4 tap = tex2Dfetch(stSPECGI_Radiance6, round(tap_uv * src_size));
        float w = exp(-dot(downsample_offsets[j], downsample_offsets[j]) / 3.5) * Math::inside_screen(tap_uv); 
        logsum += float4(logluv_to_rgb(tap) * w, w); 
    }

    logsum.rgb /= logsum.w;
    tex2Dstore(stSPECGI_Radiance7, i.dispatchthreadid.xy, rgb_to_logluv(logsum.rgb));    
}

/*=============================================================================
	Tracing
=============================================================================*/

struct TraceContext
{
    float2 uv;
    uint2 texel; //xy: working pos, zw: write pos
    float3 pos; //view space position
    float3 normal;
    float3 viewdir;
    float depth;
    float4 jitter;
    float3 geonormal;
};

TraceContext _TraceContext(in CSIN i, in uint2 working_size)
{
    TraceContext o;    
    o.texel     = i.groupid.xy * 16 + SFC::morton_i_to_xy(i.threadid);
    o.jitter.xyz= tex2Dfetch(sSPECGI_STBN128, (i.dispatchthreadid.xy & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u).xyz;
    o.jitter.w  = tex2Dfetch(sSPECGI_STBN128, ((i.dispatchthreadid.xy + 32) & 63u) + uint2((FRAMECOUNT + 26) & 15u, ((FRAMECOUNT + 26) >> 4) & 7u) * 64u).x;

    o.uv        = pixel_idx_to_uv(o.texel, working_size); 
    o.depth     = Depth::get_linear_depth(o.uv);
    o.pos       = Camera::uv_to_proj(o.uv, Camera::depth_to_z(o.depth));
    o.normal    = Deferred::get_normals(o.uv);
    o.viewdir   = normalize(o.pos);
    o.geonormal = Deferred::get_geometry_normals(o.uv);
    o.pos      *= 0.998; 
    return o;
}

float4 trace_hiz(TraceContext ctx, float3 raydir_vs)
{  
    if(raydir_vs.z < 0) return 0;
    float3 origin_vs  = ctx.pos;
    float3 origin_cs  = proj_to_clip(origin_vs);
    float3 dir_cs     = proj_to_clip(origin_vs + raydir_vs) - origin_cs; dir_cs = normalize(dir_cs);//dir_cs *= rsqrt(dot(dir_cs.xy, dir_cs.xy)); //normalize in XY
    float3 dir_cs_inv = rcp(dir_cs);

    float3 dir_sign   = Math::fast_sign(dir_cs);    
    float2 step_offs  = BUFFER_PIXEL_SIZE_DLSS * dir_sign.xy;
    dir_sign          = saturate(dir_sign); 
    float3 intercept  = float3(origin_cs.xy - step_offs, origin_cs.z) * dir_cs_inv;

    float2 uv        = origin_cs.xy + step_offs * 0.51; //avoid self intersect
    float2 level_res = BUFFER_SCREEN_SIZE_DLSS;
    int2 texel       = int2(uv * level_res);    

    int   level = 1;  //avoid self intersect
    float t     = 0;
    float last_t_above_surface = 0;    
      
    [loop]
    for(int j = 0; j < 512; j++)
    {      
        float txy = minc((texel + dir_sign.xy) / level_res * dir_cs_inv.xy - intercept.xy);
        float2 tz = tex2Dfetch(sSPECGI_QuadTree, texel, level).xy * dir_cs_inv.zz - intercept.zz; 

        [flatten]
        if(tz.x > txy || tz.y < t)
        {            
            t = txy;
            uv = origin_cs.xy + dir_cs.xy * t; 

            int2 nodes_changed = texel ^ int2(uv * level_res);   
            level = min(level + firstbithigh(nodes_changed.x | nodes_changed.y), 7); 

            [flatten] 
            if(tz.x > txy) 
            {
                last_t_above_surface = t;   
            }       
        }
        else
        {                           
            t = max(t, tz.x);
            uv = origin_cs.xy + dir_cs.xy * t; 

            --level;              
        }

        level_res = BUFFER_SCREEN_SIZE_DLSS * exp2(-level);
        texel     = floor(uv * level_res); 

        if(!Math::inside_screen(uv) || level < 0) break; 
    }

    float3 hitpos_cs = origin_cs + dir_cs * t;
    float3 hitpos_vs = clip_to_proj(hitpos_cs);

    bool hit = level < 0;
    float t_vs = distance(hitpos_vs, origin_vs);
#if 0
    //fallback at plane intersect with normal
    if(!hit)
    {
        float3 surfacepos_cs;
        surfacepos_cs.xy = origin_cs.xy + dir_cs.xy * last_t_above_surface;     
        surfacepos_cs.z = tex2Dfetch(sSPECGI_QuadTree, int2(surfacepos_cs.xy * BUFFER_SCREEN_SIZE_DLSS), 0).x;   
        
        float3 surfacepos_vs    = clip_to_proj(surfacepos_cs);
        float3 surfacenormal_vs = Deferred::get_geometry_normals(surfacepos_cs.xy);
        
        t_vs = dot(surfacenormal_vs, surfacepos_vs - origin_vs) / dot(surfacenormal_vs, raydir_vs);
        hitpos_vs = origin_vs + raydir_vs * t_vs;                
        
        hitpos_cs = proj_to_clip(hitpos_vs);
        hit = Math::inside_screen(hitpos_cs.xy); //revalidate fallback hit
    }  
#endif
    return float4(hitpos_cs.xy, t_vs, hit); 
}

TraceContext _TraceContextThreadid(in CSIN i, in uint2 working_size)
{
    TraceContext o;    
    o.texel = i.dispatchthreadid.xy;
    o.jitter = tex2Dfetch(sSPECGI_STBN128, (i.dispatchthreadid.xy & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u).xyz;
    o.uv        = pixel_idx_to_uv(o.texel, working_size); 
    o.depth     = Depth::get_linear_depth(o.uv);
    o.pos       = Camera::uv_to_proj(o.uv, Camera::depth_to_z(o.depth));
    o.normal    = Deferred::get_normals(o.uv);
    o.viewdir   = normalize(o.pos);
    o.geonormal = Deferred::get_geometry_normals(o.uv);
    o.pos      *= 0.998;    
    return o;
}

float4 raytrace_ggx(CSIN i, TraceContext ctx)
{
    int num_rays = SPECULAR_GI_Q + 1;

    float3 V    = -ctx.viewdir;
    float3 N    = ctx.normal;
    float NdotV = saturate(dot(V, N) - 0.001) + 0.001;
    float alpha = GGX_ALPHA;

    float4 spec      = 0;
    float3 mv_at_hit = 0;

    [loop]
    for(int r = 0; r < num_rays; r++)    
    {
        float2 rand = float2((r + ctx.jitter.y)/num_rays, QMC::roberts1(r, ctx.jitter.x));  

        float pdf_ratio;
        float3 H = BXDF::GGX::sample_vndf_bounded_iso(V, N, alpha, rand.xy, 0.7, pdf_ratio);
        float3 L = reflect(-V, H);   
 
        float VdotH = saturate(dot(V, H));
        float NdotL = saturate(dot(L, N)); 

        float F0 = saturate(RT_FRESNEL_F0);
        float F = BXDF::fresnel_schlick(VdotH, F0);
        float G2overG1 = BXDF::GGX::smith_G2_over_G1_heightcorrelated(alpha, NdotL, NdotV);             
        float estimator = pdf_ratio * F * G2overG1;

        estimator *= saturate(L.z); //only allow forward rays, makes it easier in HiZ tracing too
        estimator *= step(0, dot(L, ctx.geonormal)); 

        if(estimator > 0.001)
        {
            float4 hit_info = trace_hiz(ctx, L);
            if(hit_info.w)
            {
                float3 Ni = Deferred::get_geometry_normals(hit_info.xy);
                float facing = saturate(-dot(Ni, L) * 32); 

                float2 randdelta = rand.xy > 0.5.xx ? 0.01.xx : -0.01.xx;
                float3 HX = BXDF::GGX::sample_vndf_bounded_iso(V, N, alpha, rand.xy + float2(randdelta.x, 0), 0.7, pdf_ratio);
                float3 HY = BXDF::GGX::sample_vndf_bounded_iso(V, N, alpha, rand.xy + float2(0, randdelta.y), 0.7, pdf_ratio);
                float3 LX = reflect(-V, HX);   
                float3 LY = reflect(-V, HY);
                float2 uvgrad_x = hit_info.xy - Camera::proj_to_uv(ctx.pos + LX * hit_info.z);    
                float2 uvgrad_y = hit_info.xy - Camera::proj_to_uv(ctx.pos + LY * hit_info.z);

                const float mip_scale = exp2(4.0);
                uvgrad_x *= mip_scale;
                uvgrad_y *= mip_scale;        
                float3 Li = logluv_to_rgb(tex2Dgrad(sSPECGI_RadianceAnisotropic, hit_info.xy, uvgrad_x, uvgrad_y));                

                Li *= saturate(5 - 5 * abs(hit_info.x * 2 - 1)) * saturate(5 - 5 * abs(hit_info.y * 2 - 1));
                spec.rgb += Li * (facing * estimator);
                spec.w   += hit_info.z;
                
                mv_at_hit += float3(estimator * Deferred::get_motion(hit_info.xy), estimator); 
            }     
        }         
    }
    spec /= num_rays; 

    float fade = get_fade_factor(ctx.depth);
    spec *= fade;

    spec.rgb /= get_brdf(NdotV, alpha);    

    mv_at_hit /= num_rays; //normalize later by estimator so we can pool multiple pixels if this one didn't hit anything
    tex2Dstore(stSPECGI_HitVectors, ctx.texel, float4(mv_at_hit, 1));
    return spec;
}

void TraceWrapCS(in CSIN i)
{   
    TraceContext ctx = _TraceContextThreadid(i, BUFFER_SCREEN_SIZE_DLSS);
    float4 spec = raytrace_ggx(i, ctx);
    tex2Dstore(stSPECGI_Aux0, ctx.texel.xy, spec);
}

float3 ray_plane_intersection(float3 p_plane, float3 n_plane, float3 origin, float3 dir)
{
    float t = dot(n_plane, p_plane - origin) / dot(n_plane, dir);
    return origin + t * dir;
}

float get_max_spp_from_alpha(float alpha)
{
    return lerp(8, 128, sqrt(alpha));
}

void TemporalBlendPS(in VSOUT i, out PSOUT2 o)
{
    float4 curr_spec = tex2D(sSPECGI_Aux0, i.uv);
    
    float2 prev_uv = i.uv + Deferred::get_motion(i.uv);
    //prev_uv = i.uv + float2(1, 1) * BUFFER_PIXEL_SIZE_DLSS;
    bool inside_screen = Math::inside_screen(prev_uv); 
    bool valid_history = inside_screen;

    float3 n = Deferred::get_normals(i.uv);
    float3 p = Camera::uv_to_proj(i.uv);    
    float  z = p.z;

    float alpha = GGX_ALPHA;
    float3 viewdir = -normalize(Camera::uv_to_proj(i.uv, 1));
    float3 eta1 = BXDF::GGX::dominant_direction(n, viewdir, alpha);
    
    //if(i.uv.y > 0.5)
    {
        float4 tempv = tex2Dlod(sSPECGI_HitVectors, i.uv, 4);
        float2 motionvec_there = tempv.xy / (tempv.z + 1e-6);       
        prev_uv = i.uv + motionvec_there;       
    }

    float4 prev_spec = tex2D(sSPECGI_Accum, prev_uv);
  
    float4 prev_stats = 0;
    float prev_confidence = 0;

    float2 curr_hit_t_moments = 0;
    float3 m1_signal = 0, m2_signal = 0;
    
    for(int x = -2; x <= 2; ++x)
    for(int y = -2; y <= 2; ++y)
    {
        float t = tex2Dfetch(sSPECGI_Aux0, i.vpos.xy + int2(x, y)).w;
        curr_hit_t_moments += float2(t, t*t);
    }

    curr_hit_t_moments /= 25.0;
    float mean_hit_t = curr_hit_t_moments.x;
    float var_hit_t = (max(0, curr_hit_t_moments.y - curr_hit_t_moments.x * curr_hit_t_moments.x));   

    [branch]
    if(inside_screen)
    {
        float2 texel_uv = prev_uv * BUFFER_SCREEN_SIZE_DLSS - 0.5;
        int2 texel_lower = floor(texel_uv);
        float2 bilinear_kernel = frac(texel_uv);
        float2 quad_center_uv = (texel_lower + 1.0) * BUFFER_PIXEL_SIZE_DLSS;
        float4 bilinX = float4(0, 1 - frac(texel_uv.x), frac(texel_uv.x), 0);
        float4 bilinY = float4(0, 1 - frac(texel_uv.y), frac(texel_uv.y), 0); 

        float4 bilinear_weights; 
        bilinear_weights.x = (1 - bilinear_kernel.x) * (1 - bilinear_kernel.y);
        bilinear_weights.y =      bilinear_kernel.x  * (1 - bilinear_kernel.y);
        bilinear_weights.z = (1 - bilinear_kernel.x) *      bilinear_kernel.y;
        bilinear_weights.w =      bilinear_kernel.x  *      bilinear_kernel.y;        

        float4 octnx = tex2DgatherR(sSPECGI_PrevNormals, (texel_lower + 1.0) * BUFFER_PIXEL_SIZE_DLSS).wzxy;
        float4 octny = tex2DgatherG(sSPECGI_PrevNormals, (texel_lower + 1.0) * BUFFER_PIXEL_SIZE_DLSS).wzxy;

        float3 n00 = Math::octahedral_dec(float2(octnx.x, octny.x));
        float3 n10 = Math::octahedral_dec(float2(octnx.y, octny.y));
        float3 n01 = Math::octahedral_dec(float2(octnx.z, octny.z));
        float3 n11 = Math::octahedral_dec(float2(octnx.w, octny.w));
        
        float3 viewdir_prev = -normalize(Camera::uv_to_proj(prev_uv, 1.0)); //simpler to just use that one for all
        float3 eta2_00 = BXDF::GGX::dominant_direction(n00, viewdir_prev, alpha);
        float3 eta2_10 = BXDF::GGX::dominant_direction(n10, viewdir_prev, alpha);
        float3 eta2_01 = BXDF::GGX::dominant_direction(n01, viewdir_prev, alpha);
        float3 eta2_11 = BXDF::GGX::dominant_direction(n11, viewdir_prev, alpha);

        float4 reject_n;
        reject_n.x = sg_overlap(eta1, eta2_00, alpha, alpha, 2.0);
        reject_n.y = sg_overlap(eta1, eta2_10, alpha, alpha, 2.0);
        reject_n.z = sg_overlap(eta1, eta2_01, alpha, alpha, 2.0);
        reject_n.w = sg_overlap(eta1, eta2_11, alpha, alpha, 2.0);

        float4 prev_spec00 = tex2Dfetch(sSPECGI_Accum, texel_lower + int2(0, 0));
        float4 prev_spec10 = tex2Dfetch(sSPECGI_Accum, texel_lower + int2(1, 0)); 
        float4 prev_spec01 = tex2Dfetch(sSPECGI_Accum, texel_lower + int2(0, 1));
        float4 prev_spec11 = tex2Dfetch(sSPECGI_Accum, texel_lower + int2(1, 1));

        float scale = 0.25;
        float4 prev_hit_t = float4(prev_spec00.w, prev_spec10.w, prev_spec01.w, prev_spec11.w);
        float4 reject_z = var_hit_t / (1e-10 + var_hit_t + (prev_hit_t - mean_hit_t) * (prev_hit_t - mean_hit_t) * scale);
        reject_z = dot(reject_z, 1) < 0.00001.xxxx ? 1.0.xxxx : reject_z;

        float4 w_bilateral = reject_n * reject_z * bilinear_weights;
        prev_confidence = dot(w_bilateral, 1);  
         
        prev_spec  = prev_spec00 * w_bilateral.x + prev_spec10 * w_bilateral.y + prev_spec01 * w_bilateral.z + prev_spec11 * w_bilateral.w;
        prev_spec /= 1e-6 + prev_confidence;

        prev_stats  = tex2Dfetch(sSPECGI_PrevTemporalHints, texel_lower + int2(0, 0)) * w_bilateral.x;
        prev_stats += tex2Dfetch(sSPECGI_PrevTemporalHints, texel_lower + int2(1, 0)) * w_bilateral.y; 
        prev_stats += tex2Dfetch(sSPECGI_PrevTemporalHints, texel_lower + int2(0, 1)) * w_bilateral.z; 
        prev_stats += tex2Dfetch(sSPECGI_PrevTemporalHints, texel_lower + int2(1, 1)) * w_bilateral.w;
        prev_stats /= 1e-6 + prev_confidence;              
    }
    
    //first, compute optimal interpolant to maximize SPP based on weighted history SPP
    float prev_spp = max(1, prev_stats.z);
    float curr_spp = 1;

    float max_spp = get_max_spp_from_alpha(alpha);
    float combined_spp = min(max_spp, curr_spp + prev_spp * prev_confidence);
    float interpolant = curr_spp / combined_spp; //for a prev_confidence of 0, this comes out as 1/(1 + 0)      

    //calculate effective SPP which are a combination of the unnormalized spp
    //this harmonizes with the previous interpolant formula, i.e. if interpolant is unchanged, this returns effective_spp == combined_spp    
    float effective_spp = min(curr_spp / max(interpolant, 0.001), max(1, prev_spp) / max(0.001, 1.0 - interpolant));

    //this harmonizes with that other formula! Just need to use the normalized prev_spp  
    o.t0 = lerp(prev_spec, curr_spec, interpolant);
    
    o.t1.x = lerp(prev_stats.x, curr_spec.w,               interpolant);
    o.t1.y = lerp(prev_stats.y, curr_spec.w * curr_spec.w, interpolant);
    o.t1.z = effective_spp;
    o.t1.w = curr_spec.w; //directly store prev hit_t   
}

float2x2 make_skew_matrix(float2 d, float limit)
{
    float2 a = d * limit;
    float c = rsqrt(1 - dot(a, a));
    float3 t = d.xxy * d.xyy * (c * c);
    t.xz = c - t.xz;
    return float2x2(t.z, t.y, t.y, t.x); //ReShade FX compiler bug in 6.6, t.zyyx doesn't work.
}

void denoise_pass(in VSOUT i, sampler s_spec, int iter, out PSOUT2 filter_out)
{
    int2 texel = i.vpos.xy;
    float3 n_center = Deferred::get_normals(i.uv);    
    float3 gn_center = Deferred::get_geometry_normals(i.uv);   
    float spp = max(1, tex2Dfetch(sSPECGI_Aux2, texel).z);   

    float alpha = GGX_ALPHA;
    float4 spec_center = tex2Dfetch(s_spec, texel);      

    float3 p_center = Camera::uv_to_proj(i.uv, 1);
    float3 v_center = -normalize(p_center);
    float3 D_center = BXDF::GGX::dominant_direction(n_center, v_center, alpha);
    float NdotD     = dot(D_center, gn_center); 
    float NdotV     = saturate(dot(v_center, n_center) - 0.001) + 0.001;
    float hit_t     = spec_center.w;     

    float max_spp = get_max_spp_from_alpha(alpha);
    float convergence = spp / max_spp;

    float kernel_scale = NdotD * hit_t / (p_center.z + hit_t * D_center.z); 
    kernel_scale *= 8.0;
    kernel_scale *= alpha;
    kernel_scale *= lerp(10, 1, sqrt(convergence));
    kernel_scale = clamp(kernel_scale, 1, 20);

    float2x2 kernel_matrix = make_skew_matrix(gn_center.xy, 0.7) * kernel_scale;
    kernel_matrix[0][0] *= BUFFER_PIXEL_SIZE_DLSS.x;
    kernel_matrix[0][1] *= BUFFER_PIXEL_SIZE_DLSS.x;
    kernel_matrix[1][0] *= BUFFER_PIXEL_SIZE_DLSS.y;
    kernel_matrix[1][1] *= BUFFER_PIXEL_SIZE_DLSS.y;

    float4 filter_sum = 0;
    float filter_wsum = 0;

    float per_frame_rand = QMC::roberts1(FRAMECOUNT);
    float2 jitter = QMC::roberts2(FRAMECOUNT % 128);
    int samples = 2;
    const int dirs = 6;    

    float3 minv = 1e10;
    float3 maxv = 0;

    float beta = lerp(0.0, 12.0, sqrt(convergence));
    
    //TODO optimize with rotation matrix etc.
    [unroll]for(int dir = 0; dir < dirs; ++dir)
    [unroll]for(int stp = 1; stp <= samples; ++stp)
    {
        float2 kernel; 
        sincos((QMC::roberts1(stp) + dir + per_frame_rand) / 6.0 * TAU, kernel.y, kernel.x);       
        kernel *= sqrt(stp);
        float2 tap_uv = i.uv + mul(kernel_matrix, kernel);
        
        float3 n_tap = Deferred::get_normals(tap_uv);
        float3 v_tap = -normalize(Camera::uv_to_proj(tap_uv, 1));
        float4 signal_tap = tex2Dlod(s_spec, tap_uv, 0);

        float3 D_tap = BXDF::GGX::dominant_direction(n_tap, v_tap, alpha);
        float wn = sg_overlap(D_center, D_tap, alpha, alpha, beta);    

        //float wz = abs(signal_tap.w - spec_center.w) / max3(0.001, spec_center.w, signal_tap.w);
        //wz = exp(-wz * 16.0);
        float w = wn;// * wz;    

        minv = min(minv, signal_tap.rgb);
        maxv = max(maxv, signal_tap.rgb); 

        filter_sum  += signal_tap * w;
        filter_wsum += w;
    }

    spec_center.rgb = clamp(spec_center.rgb, minv, maxv); 
    filter_sum += spec_center;
    filter_wsum++;
    filter_sum /= filter_wsum; 

    filter_out.t0 = filter_out.t1 = filter_sum;
    filter_out.t1.rgb *= get_brdf(NdotV, alpha);
}

void DenoisePS(in VSOUT i, out PSOUT2 o){denoise_pass(i, sSPECGI_Aux1, 0, o);}

void UpdatePrevBuffersCS(in CSIN i)
{
    float4 spec  = tex2Dfetch(sSPECGI_Aux3, i.dispatchthreadid.xy);
    float4 hints = tex2Dfetch(sSPECGI_Aux2, i.dispatchthreadid.xy);
    float2 normals = Math::octahedral_enc(Deferred::get_normals((i.dispatchthreadid.xy + 0.5) * BUFFER_PIXEL_SIZE_DLSS));

    tex2Dstore(stSPECGI_Accum,             i.dispatchthreadid.xy, spec);
    tex2Dstore(stSPECGI_PrevTemporalHints, i.dispatchthreadid.xy, hints);
    tex2Dstore(stSPECGI_PrevNormals,       i.dispatchthreadid.xy, normals.xyyy);
}

/*=============================================================================
	TAAU Compatibility Layer
=============================================================================*/

#ifdef _MARTYSMODS_TAAU_SCALE

texture SPECGI_TAAU_SpecularBeta   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture SPECGI_TAAU_SpecularCov    { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sSPECGI_TAAU_SpecularBeta  { Texture = SPECGI_TAAU_SpecularBeta; };
sampler sSPECGI_TAAU_SpecularCov   { Texture = SPECGI_TAAU_SpecularCov; };
storage stSPECGI_TAAU_SpecularBeta  { Texture = SPECGI_TAAU_SpecularBeta; };
storage stSPECGI_TAAU_SpecularCov   { Texture = SPECGI_TAAU_SpecularCov; };

void taau_resolve(in VSOUT i, 
                  sampler s_prev_beta, 
                  sampler s_prev_cov, 
                  sampler s_curr, 
                  out float4 new_beta, 
                  out float4 new_cov)
{
    float2 prev_uv = i.uv + Deferred::get_motion(i.uv);
    float4 m1 = 0;
    float4 m2 = 0;

    int r = 2;

    [unroll]for(int x = -r; x <= r; x++)
    [unroll]for(int y = -r; y <= r; y++)
    {
        float4 tap = tex2Dfetch(s_curr, int2(i.vpos.xy) + int2(x, y));
        m1 += tap; m2 += tap * tap;
    }

    m1 /= (r*2+1)*(r*2+1); m2 /= (r*2+1)*(r*2+1);

    float4 curr_mean = m1;
    float4 curr_sigma = sqrt(abs(m2 - m1 * m1));

    float lambda = 0.9;

    float4 old_beta = tex2D(s_prev_beta, prev_uv);
    float4 old_cov  = tex2D(s_prev_cov, prev_uv);
    float4 curr_value = tex2D(s_curr, i.uv);

    float fallback = 1000;

    if(!Math::inside_screen(prev_uv))
    {
        [flatten]if(abs(old_cov.x) < 1e-7) old_beta.x = curr_value.x, old_cov.x = fallback;//10.0;
        [flatten]if(abs(old_cov.y) < 1e-7) old_beta.y = curr_value.y, old_cov.y = fallback;//10.0;
        [flatten]if(abs(old_cov.z) < 1e-7) old_beta.z = curr_value.z, old_cov.z = fallback;//10.0;
        [flatten]if(abs(old_cov.w) < 1e-7) old_beta.w = curr_value.w, old_cov.w = fallback;//10.0;
    }

    float4 predicted_value = old_beta;
    float4 deviations_from_target = abs(predicted_value - curr_mean) / max(1e-7, curr_sigma);          
    float4 clamped = clamp(predicted_value, curr_mean - curr_sigma, curr_mean + curr_sigma);  

    [unroll]
    for(int j = 0; j < 4; j++)
    {
        [branch]
        if(predicted_value[j] != clamped[j])
        {
            float clamp_strength = (deviations_from_target[j] - 1) / (deviations_from_target[j] + 1e-5);
            predicted_value[j] = old_beta[j] = clamped[j];
            old_cov[j] = lerp(old_cov[j], fallback, clamp_strength);
        }
    }

    float4 error = curr_value - predicted_value;
    float4 Q_t = old_cov / (lambda + old_cov);

    new_beta = old_beta + Q_t * error;
    new_cov = (old_cov - Q_t * old_cov) / lambda;
}

void TAAUResolvePS(in VSOUT i, out PSOUT2 o)
{
    o.t0 = o.t1 = 0;
    taau_resolve(i, sSPECGI_TAAU_SpecularBeta, sSPECGI_TAAU_SpecularCov, sSPECGI_Aux0, o.t0, o.t1);       
}

void TAAUUpdateHistoryCS(in CSIN i)
{
    const int groupsize = 8;
    int2 p = i.groupid.xy * groupsize * 2 + SFC::morton_i_to_xy(i.threadid).yx;
    int2 p00 = p;
    int2 p01 = int2(p.x + groupsize, p.y);
    int2 p10 = int2(p.x, p.y + groupsize);
    int2 p11 = int2(p.x + groupsize, p.y + groupsize);
    //no storages as function parameters means copypaste goes brr
    {
        float4 t00 = tex2Dfetch(sSPECGI_Aux2, p00);
        float4 t01 = tex2Dfetch(sSPECGI_Aux2, p01);
        float4 t10 = tex2Dfetch(sSPECGI_Aux2, p10);
        float4 t11 = tex2Dfetch(sSPECGI_Aux2, p11);

        tex2Dstore(stSPECGI_TAAU_SpecularBeta, p00, t00);
        tex2Dstore(stSPECGI_TAAU_SpecularBeta, p01, t01);
        tex2Dstore(stSPECGI_TAAU_SpecularBeta, p10, t10);
        tex2Dstore(stSPECGI_TAAU_SpecularBeta, p11, t11);
    }
    {
        float4 t00 = tex2Dfetch(sSPECGI_Aux3, p00);
        float4 t01 = tex2Dfetch(sSPECGI_Aux3, p01);
        float4 t10 = tex2Dfetch(sSPECGI_Aux3, p10);
        float4 t11 = tex2Dfetch(sSPECGI_Aux3, p11);

        tex2Dstore(stSPECGI_TAAU_SpecularCov, p00, t00);
        tex2Dstore(stSPECGI_TAAU_SpecularCov, p01, t01);
        tex2Dstore(stSPECGI_TAAU_SpecularCov, p10, t10);
        tex2Dstore(stSPECGI_TAAU_SpecularCov, p11, t11);
    }        
}

#endif //_MARTYSMODS_TAAU_SCALE  

/*=============================================================================
	Blending
=============================================================================*/

void OutPS(in VSOUT i, out float3 o : SV_Target0)
{
#ifdef _MARTYSMODS_TAAU_SCALE
    o = tex2D(sSPECGI_Aux2, i.uv).rgb;  
#else 
    o = tex2D(sSPECGI_Aux0, i.uv).rgb;  
#endif
    if(RT_DEBUG_VIEW == 0)
    {
        o += unpack_hdr(tex2Dlod(ColorInput, i.uv, 0).rgb);  
    }
    else if(RT_DEBUG_VIEW == 1)
    {
        o *= 16.0;
    }
    o = pack_hdr(o);

    if(RT_DEBUG_VIEW == 2)
    {
        float2 scaled_uv = i.uv * 4.0;
        int2 layer = int2(scaled_uv);
        scaled_uv = frac(scaled_uv);

        if(layer.x == 0)
        {    
#ifdef _MARTYSMODS_TAAU_SCALE
            float3 tiled_spec = tex2Dlod(sSPECGI_Aux2, scaled_uv, 0).rgb;
#else 
            float3 tiled_spec = tex2Dlod(sSPECGI_Aux0, scaled_uv, 0).rgb;
#endif
            float3 tiled_color = unpack_hdr(tex2Dlod(ColorInput, scaled_uv, 0).rgb);

            o = layer.y == 0 ? Debug::viridis(Depth::get_linear_depth(scaled_uv)) 
            : layer.y == 1 ? pack_hdr(tiled_spec)
            : layer.y == 2 ? Deferred::get_normals(scaled_uv) * 0.5 * float3(1,-1,-1) + 0.5
            : layer.y == 3 ? showmotion(Deferred::get_motion(scaled_uv))
            : o;
        }
    }
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_SPECGI_Specular
<
    ui_label = "iMMERSE Pro: RTGI (Specular)";
    ui_tooltip =        
        "                         MartysMods - RTGI (Specular)                             \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "RTGI adds fully dynamic, realistic and immersive ray traced lighting to your games\n"
        "to enhance existing lighting or to completely relight your scene, depending on the\n"
        "use case.\n"
        "Make sure iMMERSE LAUNCHPAD is enabled and placed at the top of the effect list!    "
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n"
        "Version: S-1.1";
>
{  
    pass { VertexShader = MainVS; PixelShader = RadianceMiptreePS; RenderTarget = SPECGI_Radiance; GenerateMipMaps = false;}  
    pass { ComputeShader = DownsampleRadianceCS0<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/2, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/2, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS1<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/4, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS2<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/8, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/8, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS3<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/16, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/16, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS4<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/32, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/32, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS5<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/64, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/64, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = DownsampleRadianceCS6<16, 16>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/128, 16);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/128, 16);  GenerateMipMaps = false;}    
    pass { ComputeShader = SpecularHiZDownsampleCS<32, 32>;     DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS, 32*4);  DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS, 32*4);  GenerateMipMaps = false;}    
    pass { ComputeShader = TraceWrapCS<8, 8>;                   DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS, 8);     DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS, 8); }      
    pass { VertexShader = MainVS; PixelShader = TemporalBlendPS; RenderTarget0 = SPECGI_Aux1; RenderTarget1 = SPECGI_Aux2; }    
    pass { VertexShader = MainVS; PixelShader = DenoisePS; RenderTarget0 = SPECGI_Aux3; RenderTarget1 = SPECGI_Aux0;} //1, 2 -> 3, 0
    pass { ComputeShader = UpdatePrevBuffersCS<16, 16>;         DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS, 16);    DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS, 16);} 
#ifdef _MARTYSMODS_TAAU_SCALE
    pass { VertexShader = MainVS; PixelShader = TAAUResolvePS;       RenderTarget0 = SPECGI_Aux2; RenderTarget1 = SPECGI_Aux3;  }
    pass { ComputeShader = TAAUUpdateHistoryCS<8, 8>;DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/2, 8);DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/2, 8); }
#endif //_MARTYSMODS_TAAU_SCALE    
    pass { VertexShader = MainVS; PixelShader = OutPS; }
}
