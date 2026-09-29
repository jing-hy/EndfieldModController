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

uniform int DIFFUSE_GI_Q <
	ui_type = "combo";
    ui_label = "Quality";
	ui_items = "Very Low\0Low\0Medium\0High\0Ultra\0";
    ui_category = "Diffuse RTGI";
> = 3;

uniform float RT_AO_AMOUNT <
	ui_type = "drag";
	ui_min = 0; ui_max = 10.0;
    ui_label = "Ambient Occlusion Intensity";
    ui_category = "Diffuse RTGI";
> = 10.0;

uniform float RT_IL_AMOUNT <
	ui_type = "drag";
	ui_min = 0; ui_max = 10.0;
    ui_label = "Bounce Lighting Intensity";
    ui_category = "Diffuse RTGI";
> = 10.0;

uniform float RT_Z_THICKNESS <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
    ui_label = "Object Thickness";
    ui_tooltip = "The shader does not know how much objects extend beyond the visible side\nand has to assume a fixed value.\n\nSet this value as low as possible without losing GI intensity.";
	ui_category = "Diffuse RTGI";
> = 0.25;

uniform int DENOISER_Q <
	ui_type = "combo";
    ui_label = "Quality";
	ui_items = "Low\0Medium\0High\0";
    ui_category = "Denoiser";
> = 1;

uniform float FILTER_SMOOTHNESS <
	ui_type = "drag";
	ui_min = 0; ui_max = 1.0;
    ui_label = "Smoothness";
    ui_category = "Denoiser";
> = 0.5;

uniform float RT_AMBIENT_LEVEL <
	ui_type = "drag";
    ui_label = "Ambient Level";
	ui_min = 0.25; ui_max = 1.0;
	ui_tooltip = "Ambient Lighting intensity. Lower values remove constant light from the scene for RTGI to re-add dynamic light.";
    ui_category = "Blending";
> = 0.3;

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
	ui_items = "Disabled\0Diffuse RTGI\0Validation Layer\0";
	ui_tooltip = "Validation Layer:\n\n- Depth\n- Lighting\n- Normal Vectors\n- Optical Flow\n- Albedo";
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
texture NEWGI_STBN128     < source = "iMMERSE_bluenoise_temporal128.png"; >   { Width = 1024; Height = 512; Format = RGBA8; };
sampler	sNEWGI_STBN128    { Texture = NEWGI_STBN128; };
texture NEWGI_STBN128_s   < source = "iMMERSE_bluenoise_temporal128_s.png"; > { Width = 1024; Height = 512; Format = RGBA8; };
sampler	sNEWGI_STBN128_s  { Texture = NEWGI_STBN128_s; };
texture NEWGI_HorizonLUT  < source = "iMMERSE_horizonlut.png"; >              { Width = 32;   Height = 16;  Format = R8; };
sampler	sNEWGI_HorizonLUT { Texture = NEWGI_HorizonLUT; };

//GI inputs
texture NEWGI_Z     { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = R16F; MipLevels = 5;};
sampler sNEWGI_Z	{ Texture = NEWGI_Z;  MIN_MAG_MIP_POINT};
storage stNEWGI_Z0	{ Texture = NEWGI_Z;  MipLevel = 0;};
storage stNEWGI_Z1	{ Texture = NEWGI_Z;  MipLevel = 1;};
storage stNEWGI_Z2	{ Texture = NEWGI_Z;  MipLevel = 2;};
storage stNEWGI_Z3	{ Texture = NEWGI_Z;  MipLevel = 3;};
storage stNEWGI_Z4	{ Texture = NEWGI_Z;  MipLevel = 4;};

texture3D NEWGI_SHVolume    { Width = BUFFER_WIDTH_DLSS/4; Height = BUFFER_HEIGHT_DLSS/4; Depth = 5 * 3; Format = RGBA16F;};
sampler3D sNEWGI_SHVolume	{ Texture = NEWGI_SHVolume;  MIN_MAG_MIP_POINT};
storage3D stNEWGI_SHVolume	{ Texture = NEWGI_SHVolume; };

//Working buffers
texture NEWGI_STSGCache     { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = R32F; };
storage stNEWGI_STSGCache   { Texture = NEWGI_STSGCache; };
texture NEWGI_Aux0   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; MipLevels = 4;};
texture NEWGI_Aux1   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture NEWGI_Aux2   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture NEWGI_Aux3   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sNEWGI_Aux0	 { Texture = NEWGI_Aux0; MIN_MAG_MIP_POINT};
sampler sNEWGI_Aux1	 { Texture = NEWGI_Aux1; };
sampler sNEWGI_Aux2	 { Texture = NEWGI_Aux2; };
sampler sNEWGI_Aux3	 { Texture = NEWGI_Aux3; };
storage stNEWGI_Aux0 { Texture = NEWGI_Aux0; };
storage stNEWGI_Aux1 { Texture = NEWGI_Aux1; };
storage stNEWGI_Aux2 { Texture = NEWGI_Aux2; };
storage stNEWGI_Aux3 { Texture = NEWGI_Aux3; };

texture NEWGI_SpatialMoments  { Width = BUFFER_WIDTH_DLSS/2; Height = BUFFER_HEIGHT_DLSS/2; Format = RGBA16F; };
sampler sNEWGI_SpatialMoments { Texture = NEWGI_SpatialMoments; };
storage stNEWGI_SpatialMoments { Texture = NEWGI_SpatialMoments; };

texture NEWGI_AccumDiff  { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sNEWGI_AccumDiff { Texture = NEWGI_AccumDiff; };
storage stNEWGI_AccumDiff { Texture = NEWGI_AccumDiff; };

texture NEWGI_PrevTemporalData  { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sNEWGI_PrevTemporalData { Texture = NEWGI_PrevTemporalData; };
storage stNEWGI_PrevTemporalData { Texture = NEWGI_PrevTemporalData; };

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

float3 cone_overlap(float3 c)
{
    float k = 0.99 * 0.33;
    float2 f = float2(1 - 2 * k, k);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

float3 cone_overlap_inv(float3 c)
{
    float k = 0.99 * 0.33;
    float2 f = float2(k - 1, k) * rcp(3 * k - 1);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

float3 unpack_hdr(float3 color)
{
    color = saturate(color);
    color = cone_overlap(color);
    color = color*0.283799*((2.52405+color)*color);    
    //color = srgb_to_AgX(color);
    color = color * rcp(1.04 - saturate(color));    
    return color;
}

float3 pack_hdr(float3 color)
{
    color = 1.04 * color * rcp(color + 1.0);   
    //color = AgX_to_srgb(color);    
    color  = saturate(color);
    color = 1.14374*(-0.126893*color+sqrt(color));
    color = cone_overlap_inv(color);
    return color;     
}

float3 linear_to_ycocg(float3 c)
{
    float3 ycocg;
    ycocg.y = c.r - c.b;
    float tmp = c.b + ycocg.y * 0.5;
    ycocg.z = c.g - tmp;
    ycocg.x = tmp + ycocg.z * 0.5;
    return ycocg;
}

float3 ycocg_to_linear(float3 c)
{
    float3 rgb;
    float tmp = c.x - c.z * 0.5;    
    rgb.g = c.z + tmp;
    rgb.b = tmp - c.y * 0.5;
    rgb.r = c.y + rgb.b;
    return rgb;
}

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    return o;
}

float get_fade_factor(float depth)
{   
    if(RT_DEBUG_VIEW) return 1;

    float fade = saturate(1 - depth * depth); //fixed fade that smoothly goes to 0 at depth = 1, to multiply on top 
    float t = depth / (1e-6 + RT_FADE_DEPTH * RT_FADE_DEPTH);
    return saturate(exp2(-t) * fade - 0.01); //so it actually reaches 0    
}

bool can_earlyout(float depth)
{
    return get_fade_factor(depth) < 1e-5;
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

struct ZDownsamplePayload
{    
    float depth;
    float energy;
    float2 minmax;
};

ZDownsamplePayload reduce_z(ZDownsamplePayload a, ZDownsamplePayload b, ZDownsamplePayload c, ZDownsamplePayload d)
{
    ZDownsamplePayload combined;
    combined.minmax = 0.25 * (a.minmax + b.minmax + c.minmax + d.minmax);

    float2 minmax = pow(combined.minmax, float2(-0.125, 0.125));
    float4 depths = float4(a.depth, b.depth, c.depth, d.depth);
    float4 energy = float4(a.energy, b.energy, c.energy, d.energy);

    const float sharpness = 9.0;

    float4 weights_near = exp(-max(1, depths / minmax.x) * sharpness);
    float4 weights_faar = exp(-max(1, minmax.y / depths) * sharpness);
    weights_near *= 0.1 + energy;
    weights_faar *= 0.1 + energy;

    float wsum_near = dot(weights_near, 1);
    float wsum_faar = dot(weights_faar, 1);

    float anchor = wsum_near > wsum_faar ? minmax.x : minmax.y;
    float4 weights = wsum_near > wsum_faar ? weights_near : weights_faar; 
    float wsum = max(wsum_near, wsum_faar);

    combined.depth = dot(depths, weights) / wsum;
    combined.energy = dot(energy, weights) / wsum;

    return combined;
}

ZDownsamplePayload _ZDownsamplePayload(float depth, float3 radiance)
{
    ZDownsamplePayload ts;
    ts.depth = depth;
    ts.energy = length(unpack_hdr(radiance));   
    ts.minmax = float2(pow(ts.depth, -8.0), pow(ts.depth, 8.0));
    return ts;
}

groupshared ZDownsamplePayload tile_z[16*16];

void DownsampleDepthCS(CSIN i)
{
    uint2 p = (i.groupid.xy << 4) | SFC::morton_i_to_xy(i.threadid);
    uint4 tp; tp.xy = p * 2; tp.zw = tp.xy + 1;
   
    float2 quad_uv = tp.zw * BUFFER_PIXEL_SIZE_DLSS; 
    float4 quad_depths = tex2DgatherR(DepthInput, Depth::correct_uv(quad_uv)); 
    quad_depths = Depth::linearize(quad_depths);

#if RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN  // Flip vertically for gather order
    quad_depths = quad_depths.wzyx;     // WZ
#endif                                  // XY  
    
    float3 radianceX = tex2Dlod(ColorInput, quad_uv + BUFFER_PIXEL_SIZE_DLSS * float2(-0.5,  0.5), 0).rgb;  
    float3 radianceY = tex2Dlod(ColorInput, quad_uv + BUFFER_PIXEL_SIZE_DLSS * float2( 0.5,  0.5), 0).rgb; 
    float3 radianceZ = tex2Dlod(ColorInput, quad_uv + BUFFER_PIXEL_SIZE_DLSS * float2( 0.5, -0.5), 0).rgb;
    float3 radianceW = tex2Dlod(ColorInput, quad_uv + BUFFER_PIXEL_SIZE_DLSS * float2(-0.5, -0.5), 0).rgb;
   
    ZDownsamplePayload X = _ZDownsamplePayload(quad_depths.x, radianceX);  
    ZDownsamplePayload Y = _ZDownsamplePayload(quad_depths.y, radianceY);  
    ZDownsamplePayload Z = _ZDownsamplePayload(quad_depths.z, radianceZ);    
    ZDownsamplePayload W = _ZDownsamplePayload(quad_depths.w, radianceW); 

    tex2Dstore(stNEWGI_Z0, tp.xw, Camera::depth_to_z(X.depth));     
    tex2Dstore(stNEWGI_Z0, tp.zw, Camera::depth_to_z(Y.depth)); 
    tex2Dstore(stNEWGI_Z0, tp.zy, Camera::depth_to_z(Z.depth));  
    tex2Dstore(stNEWGI_Z0, tp.xy, Camera::depth_to_z(W.depth)); 

    ZDownsamplePayload combined = reduce_z(X, Y, Z, W); 
    tex2Dstore(stNEWGI_Z1, p, Camera::depth_to_z(combined.depth));

    tile_z[i.threadid] = combined;
    barrier();
    if(!(i.threadid & 3))
    {
        tile_z[i.threadid] = combined = reduce_z(tile_z[i.threadid], tile_z[i.threadid + 1], tile_z[i.threadid + 2], tile_z[i.threadid + 3]);
        tex2Dstore(stNEWGI_Z2, p >> 1, Camera::depth_to_z(combined.depth)); 
    }
    barrier();
    if(!(i.threadid & 15))
    {
        tile_z[i.threadid] = combined = reduce_z(tile_z[i.threadid], tile_z[i.threadid + 4], tile_z[i.threadid + 8], tile_z[i.threadid + 12]);   
        tex2Dstore(stNEWGI_Z3, p >> 2, Camera::depth_to_z(combined.depth)); 
    }
    barrier();
    if(!(i.threadid & 63))
    {
        combined = reduce_z(tile_z[i.threadid], tile_z[i.threadid + 16], tile_z[i.threadid + 32], tile_z[i.threadid + 48]);
        tex2Dstore(stNEWGI_Z4, p >> 3, Camera::depth_to_z(combined.depth));        
    }
}

/*=============================================================================
	Radiance Cache
=============================================================================*/

//2,4,8,16
void InitRadianceVolumeCS(in CSIN i)
{
    const uint2 target_size = BUFFER_SCREEN_SIZE_DLSS / 4;
    const float2 uv = (i.dispatchthreadid.xy + 0.5) / target_size;
    const float z0 = tex2Dlod(sNEWGI_Z, uv, 2).x; //quarter res depth
    const float3 n0 = Deferred::get_geometry_normals(uv);
    const float3 p0 = Camera::uv_to_proj(uv, z0);

    float wsum = 0;
    float4 shr = 0;
    float4 shg = 0;
    float4 shb = 0;  

    float sky_thresh = Camera::depth_to_z(0.999);//easier to do it this way rather than converting Z back to depth every time

    [unroll]
    for(int x = 0; x < 4; ++x)
    {
        //4 way batching, faster
        const float2 tuv0 = (i.dispatchthreadid.xy * 4 + int2(x, 0) + 0.5) * BUFFER_PIXEL_SIZE_DLSS;  
        const float2 tuv1 = (i.dispatchthreadid.xy * 4 + int2(x, 1) + 0.5) * BUFFER_PIXEL_SIZE_DLSS; 
        const float2 tuv2 = (i.dispatchthreadid.xy * 4 + int2(x, 2) + 0.5) * BUFFER_PIXEL_SIZE_DLSS; 
        const float2 tuv3 = (i.dispatchthreadid.xy * 4 + int2(x, 3) + 0.5) * BUFFER_PIXEL_SIZE_DLSS; 

        float4 tz;
        tz.x = tex2Dlod(sNEWGI_Z, tuv0, 0).x;
        tz.y = tex2Dlod(sNEWGI_Z, tuv1, 0).x;
        tz.z = tex2Dlod(sNEWGI_Z, tuv2, 0).x;
        tz.w = tex2Dlod(sNEWGI_Z, tuv3, 0).x;     
        const float3 tp0 = Camera::uv_to_proj(tuv0, tz.x);
        const float3 tp1 = Camera::uv_to_proj(tuv1, tz.y);
        const float3 tp2 = Camera::uv_to_proj(tuv2, tz.z);
        const float3 tp3 = Camera::uv_to_proj(tuv3, tz.w);

        const float3 tn0 = Deferred::get_geometry_normals(tuv0);       
        const float3 tn1 = Deferred::get_geometry_normals(tuv1); 
        const float3 tn2 = Deferred::get_geometry_normals(tuv2); 
        const float3 tn3 = Deferred::get_geometry_normals(tuv3);  

        float4 plane_dist;
        plane_dist.x = max(abs(dot(tp0 - p0, n0)), abs(dot(tp0 - p0, tn0))) / z0 * 16.0;
        plane_dist.y = max(abs(dot(tp1 - p0, n0)), abs(dot(tp1 - p0, tn1))) / z0 * 16.0;
        plane_dist.z = max(abs(dot(tp2 - p0, n0)), abs(dot(tp2 - p0, tn2))) / z0 * 16.0;
        plane_dist.w = max(abs(dot(tp3 - p0, n0)), abs(dot(tp3 - p0, tn3))) / z0 * 16.0;
        float4 w = exp(-plane_dist * plane_dist);

        const float4 sh0 = SphericalHarmonics::dir_to_sh(tn0);
        const float4 sh1 = SphericalHarmonics::dir_to_sh(tn1);
        const float4 sh2 = SphericalHarmonics::dir_to_sh(tn2);
        const float4 sh3 = SphericalHarmonics::dir_to_sh(tn3);

        float3 radiance0 = tex2Dlod(ColorInput, tuv0, 0).rgb;
        float3 radiance1 = tex2Dlod(ColorInput, tuv1, 0).rgb;
        float3 radiance2 = tex2Dlod(ColorInput, tuv2, 0).rgb;
        float3 radiance3 = tex2Dlod(ColorInput, tuv3, 0).rgb; 

        radiance0 = unpack_hdr(radiance0) * step(tz.x, sky_thresh);
        radiance1 = unpack_hdr(radiance1) * step(tz.y, sky_thresh);
        radiance2 = unpack_hdr(radiance2) * step(tz.z, sky_thresh);
        radiance3 = unpack_hdr(radiance3) * step(tz.w, sky_thresh);
      
        shr += sh0 * (radiance0.r * w.x);
        shg += sh0 * (radiance0.g * w.x);
        shb += sh0 * (radiance0.b * w.x);

        shr += sh1 * (radiance1.r * w.y);
        shg += sh1 * (radiance1.g * w.y);
        shb += sh1 * (radiance1.b * w.y);

        shr += sh2 * (radiance2.r * w.z);
        shg += sh2 * (radiance2.g * w.z);
        shb += sh2 * (radiance2.b * w.z);

        shr += sh3 * (radiance3.r * w.w);
        shg += sh3 * (radiance3.g * w.w);
        shb += sh3 * (radiance3.b * w.w);

        wsum += dot(w, 1);
    }   

    wsum = rcp(wsum + 1e-6);
    shr *= wsum;
    shg *= wsum;
    shb *= wsum;

    int3 write_pos = int3(i.dispatchthreadid.xy, 0);
    tex3Dstore(stNEWGI_SHVolume, write_pos, shr); write_pos.z += 5;
    tex3Dstore(stNEWGI_SHVolume, write_pos, shg); write_pos.z += 5;
    tex3Dstore(stNEWGI_SHVolume, write_pos, shb);
}

//v1 entire plane in parallel
void downsample_volume_pass(in CSIN i, in uint it)
{
    int dilation = 1u << it;
    
    uint2 target_size = BUFFER_SCREEN_SIZE_DLSS / 4;
    if(any(i.dispatchthreadid.xy >= target_size)) return; 

    float2 uv = (i.dispatchthreadid.xy + 0.5) / target_size;
    float  z0 = tex2Dlod(sNEWGI_Z, uv, 2).x; //quarter res depth TODO try out lower mips   
    float3 n0 = Deferred::get_geometry_normals(uv);
    float3 p0 = Camera::uv_to_proj(uv, z0);

    float4 shr = 0;
    float4 shg = 0;
    float4 shb = 0;
    float wsum = 0;

    [unroll]for(int x = -1; x <= 1; x++)
    [unroll]for(int y = -1; y <= 1; y++)    
    {
        int2 texel = i.dispatchthreadid.xy + int2(x, y) * dilation;
        float2 tuv = (texel + 0.5) / target_size;
        float  tz = tex2Dlod(sNEWGI_Z, tuv, 2).x;
        float3 tn = Deferred::get_geometry_normals(tuv);
        float3 tp = Camera::uv_to_proj(tuv, tz);

        float plane_dist = max(abs(dot(tp - p0, n0)), abs(dot(tp - p0, tn))) / z0 * 16.0;
        float w = exp(-plane_dist * plane_dist);

        w *= Math::inside_screen(tuv); //alternatively use cropminmax
        shr += tex3Dfetch(stNEWGI_SHVolume, int3(texel, it)) * w;
        shg += tex3Dfetch(stNEWGI_SHVolume, int3(texel, it + 5)) * w;
        shb += tex3Dfetch(stNEWGI_SHVolume, int3(texel, it + 10)) * w;
        wsum += w;
    }

    wsum = rcp(wsum + 1e-6);
    shr *= wsum;
    shg *= wsum;
    shb *= wsum;

    tex3Dstore(stNEWGI_SHVolume, int3(i.dispatchthreadid.xy, it + 1),      shr);
    tex3Dstore(stNEWGI_SHVolume, int3(i.dispatchthreadid.xy, it + 1 + 5),  shg);
    tex3Dstore(stNEWGI_SHVolume, int3(i.dispatchthreadid.xy, it + 1 + 10), shb);
}

void PropagateRadianceCS0(in CSIN i){downsample_volume_pass(i, 0);}
void PropagateRadianceCS1(in CSIN i){downsample_volume_pass(i, 1);}
void PropagateRadianceCS2(in CSIN i){downsample_volume_pass(i, 2);}
void PropagateRadianceCS3(in CSIN i){downsample_volume_pass(i, 3);}

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
#if 0
    o.texel = i.dispatchthreadid.xy;
    uint2 jitter_texel = (i.dispatchthreadid.xy & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u;
    o.jitter.xyz = tex2Dfetch(sNEWGI_STBN128, jitter_texel).xyz;  
    jitter_texel = (i.dispatchthreadid.yx & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u;
    o.jitter.w = tex2Dfetch(sNEWGI_STBN128, jitter_texel).x;  
#else 
    uint2 jitter_texel = (i.dispatchthreadid.xy & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u;
    float3 seed_data = tex2Dfetch(sNEWGI_STBN128_s, jitter_texel).xyz;

    o.jitter.x = seed_data.x; 
    o.texel = i.groupid.xy * 32 + int2(seed_data.yz * 255.0 + 0.5); 
    
    jitter_texel = (o.texel & 63u) + uint2(FRAMECOUNT & 15u, (FRAMECOUNT >> 4) & 7u) * 64u;
    o.jitter.yzw = tex2Dfetch(sNEWGI_STBN128, jitter_texel).xyz; 
#endif

    o.uv        = pixel_idx_to_uv(o.texel, working_size); 
    o.depth     = Depth::get_linear_depth(o.uv);
    o.pos       = Camera::uv_to_proj(o.uv, Camera::depth_to_z(o.depth));
    o.normal    = Deferred::get_normals(o.uv);
    o.viewdir   = normalize(o.pos);
    o.geonormal = Deferred::get_geometry_normals(o.uv);
    o.pos      *= 0.998; 
    return o;
}

float diffuse_sample_curve(float x)
{   
    float k = 5.0;
    return (exp2(k * x) - 1) / (exp2(k) - 1); 
}

float diffuse_sample_curve_inverse(float x)
{
    float k = 5.0;
    return log2(x * exp2(k) - x + 1) / k;
}


//quantized
#define FLOAT_TO_UINT_QUANTIZATION_SCALE     65536.0
#define NUM_DIRECTIONS                       64 //DO NOT CHANGE
#define TILE_DIMENSIONS                      8  //DO NOT CHANGE

groupshared float tgsm_pdf[1024];
groupshared float tgsm_cdf[1024];
groupshared uint  tgsm_pdf_accum[1024];

uint2 bitfieldocclusion64(float2 h_frontback, inout uint2 global_occlusion)
{
    float2 minh = linearstep(float2(0, 0.5), float2(0.5, 1), h_frontback.x);
    float2 maxh = linearstep(float2(0, 0.5), float2(0.5, 1), h_frontback.y);

    uint2 a = uint2(minh * 32);
    //uint3 b = ceil(saturate(maxh - minh) * 32);
    uint2 b = uint2(maxh * 32) - a;

    uint2 occlusion = ((1u << b) - 1u) << a;
    occlusion.x = b.x == 32 ? 0xFFFFFFFFu : occlusion.x; //full occlusion
    occlusion.y = b.y == 32 ? 0xFFFFFFFFu : occlusion.y; //full occlusion

    uint2 local_bitfield = global_occlusion & ~occlusion;
    uint2 changed_bits = local_bitfield ^ global_occlusion;
    global_occlusion = local_bitfield;
    return changed_bits;
}

float4 trace_diffuse_cdf_cubic(TraceContext ctx)
{ 
    if(!Math::inside_screen(ctx.uv) || can_earlyout(ctx.depth)) return 0;

    ctx.jitter.x = frac(ctx.jitter.x + Hash::uint_to_unorm(Hash::uhash(ctx.texel.x + ctx.texel.y * 195345)) / 255.0);  
    ctx.jitter.y = frac(ctx.jitter.y + Hash::uint_to_unorm(Hash::uhash(ctx.texel.y + ctx.texel.x * 195345)) / 255.0);  

    static const int quality_preset_steps[5] = {4, 12, 18, 32, 40};//you think you want to tamper with this, but you don't  
    static const int quality_preset_rays[5] = {1,  1,  1,  1,  1};//you think you want to tamper with this, but you don't  
   
    uint num_slices  = quality_preset_rays[DIFFUSE_GI_Q];
    uint sample_count = quality_preset_steps[DIFFUSE_GI_Q];

    float slicesum = 1e-6;
    float T = RT_Z_THICKNESS * RT_Z_THICKNESS;  //arbitrary thickness that looks good relative to sample radius

    float mip_bias = log2(BUFFER_WIDTH_DLSS) - 5.0 + (ctx.jitter.z - 0.5);

    float3 v = -ctx.viewdir;
    float3 n = ctx.normal; 

    int2 block_id = (ctx.texel % 32u) / TILE_DIMENSIONS;
    int num_blocks = 32 / TILE_DIMENSIONS;
    int flat_block_id = block_id.x + block_id.y * num_blocks;
    int block_start = flat_block_id * NUM_DIRECTIONS;

    float4 result = 0; 

    [loop]
    for(int slice_id = 0; slice_id < num_slices; slice_id++)
    {        
        float fi = float(slice_id + ctx.jitter.x) / num_slices;  
       
        int idx = block_start;
        idx = fi >= tgsm_cdf[idx + 32] ? idx + 32 : idx;
        idx = fi >= tgsm_cdf[idx + 16] ? idx + 16 : idx;
        idx = fi >= tgsm_cdf[idx +  8] ? idx +  8 : idx;      
        idx = fi >= tgsm_cdf[idx +  4] ? idx +  4 : idx;
        idx = fi >= tgsm_cdf[idx +  2] ? idx +  2 : idx;
        idx = fi >= tgsm_cdf[idx +  1] ? idx +  1 : idx;

        int local_idx = idx - block_start; 
        float cdf_this_bin = tgsm_cdf[idx];
        float cdf_next_bin = local_idx == (NUM_DIRECTIONS - 1) ? 1.0 : tgsm_cdf[idx + 1];
        float relative_pos_in_bracket = linearstep(cdf_this_bin, cdf_next_bin, fi);

        int idx_next_bin = (local_idx == (NUM_DIRECTIONS - 1)) ? block_start : idx + 1; //avoids modulo

        float pdf0 = tgsm_pdf[idx];
        float pdf1 = tgsm_pdf[idx_next_bin]; 
  
        //normalize removed here, check if bugs appear, see BAK Test 67
        float x = relative_pos_in_bracket;
        float icdf_this_bracket = (sqrt(lerp(pdf0*pdf0, pdf1*pdf1, x)) - pdf0) / (pdf1 - pdf0);//(-P + sqrt(max(0, P*P + (Q*Q - P*P) * x))) / (Q - P);

        float remapped_pos_in_bracket = abs(pdf1 - pdf0) < 1e-3 ? x : icdf_this_bracket; //avoid numerical instability  
        float pdf = lerp(pdf0, pdf1, remapped_pos_in_bracket);     

        float weight_this_bin = 1.0 - remapped_pos_in_bracket;
        float weight_next_bin = remapped_pos_in_bracket;           
        fi = (local_idx + remapped_pos_in_bracket) / NUM_DIRECTIONS;

        //actual body starts here
        float2 slice_dir; 
        sincos(fi * PI, slice_dir.y, slice_dir.x);        
      
        float3 ortho_dir = float3(slice_dir, 0) - dot(slice_dir, v.xy) * v; //z = 0 so no need for full dot3        
        float3 slice_n = cross(ortho_dir, v);
        float rcp_slice_n_len = rsqrt(dot(slice_n, slice_n)); //do not normalice slice_n, we can scale scalars with the inv len later

        float sin_n = dot(slice_n, n) * rcp_slice_n_len; //cos between slice normal and normal == sin between normal projected on slice vs normal itself
        float3 n_proj_on_slice = n - slice_n * (sin_n * rcp_slice_n_len);
        float proj_n_len = sqrt(saturate(1 - sin_n * sin_n));
        float cosn = saturate(dot(n_proj_on_slice, v) * rcp(proj_n_len+1e-6));
       
        float normal_angle = Math::fast_acos(cosn);
        normal_angle = dot(ortho_dir, n_proj_on_slice) > 0 ? normal_angle : -normal_angle;
        float sliceweight = max(0, (cosn + normal_angle * sin(normal_angle)) * proj_n_len);

        uint2 occlusion_bitfield = 0xFFFFFFFF;
   
        float2 scaled_dir = slice_dir * BUFFER_ASPECT_RATIO_DLSS; //verified 110125
        float2 initial_step = slice_dir * BUFFER_PIXEL_SIZE_DLSS;
        float4 slice_result = 0.0;

        [unroll]
        for(int side = 0; side < 2; side++)
        {    
            float2 limit_uv = Math::aabb_hit_01(ctx.uv, scaled_dir);
            float2 uv_delta = abs(limit_uv - ctx.uv);

            float dist_to_edge = length(uv_delta / BUFFER_ASPECT_RATIO_DLSS);
            int num_samples_this_dir = 1 + int(diffuse_sample_curve_inverse(dist_to_edge) * sample_count);           

            [loop]         
            for(int _sample = 0; _sample <= num_samples_this_dir; _sample++)
            { 
                float2 s = saturate((_sample + float2(0, 0.5) + ctx.jitter.y * 0.5) / sample_count); //yes actually sample count
                s.x = diffuse_sample_curve(s.x);
                s.y = diffuse_sample_curve(s.y); 
                s = min(s, dist_to_edge);  

                float mip = log2(s.y) + mip_bias;                    

                float4 tap_uvs;
                tap_uvs.xy = ctx.uv + initial_step + scaled_dir * s.x;
                tap_uvs.zw = ctx.uv + initial_step + scaled_dir * s.y;

                float2 zvals;             
                zvals.x = tex2Dlod(sNEWGI_Z, tap_uvs.xy, mip).x;
                zvals.y = tex2Dlod(sNEWGI_Z, tap_uvs.zw, mip).x;              
  
                [unroll]
                for(int pair = 0; pair < 2; pair++)
                {
                    float2 tap_uv = tap_uvs.xy;
                    float zz = zvals.x;
           
                    tap_uvs.xy = tap_uvs.zw;
                    zvals.x = zvals.y;    
   
                    float3 Lp = Camera::uv_to_proj(tap_uv, zz);          
                    float3 L1 = Lp - ctx.pos;                  
                    float3 L2 = L1 + Lp * T;  

                    float iL1L1 = rsqrt(dot(L1, L1));
                    float iL2L2 = rsqrt(dot(L2, L2));
                    float2 h = float2(dot(L1, v) * iL1L1, dot(L2, v) * iL2L2); //divide by length rather than normalize vector first, faster on scalar hardware

                    h = side ? (h * 0.25 + 0.25) : (h.yx * -0.25 + 0.75);
                    h.x = tex2Dlod(sNEWGI_HorizonLUT, float2(h.x, normal_angle / PI + 0.5), 0).x;
                    h.y = tex2Dlod(sNEWGI_HorizonLUT, float2(h.y, normal_angle / PI + 0.5), 0).x;   
                        
                    h = saturate(h + QMC::roberts1(slice_id, ctx.jitter.w) / 64.0);
                    uint2 changed_bits = bitfieldocclusion64(h, occlusion_bitfield); 

                    [branch]
                    if(any(changed_bits) && dot(L1, ctx.geonormal) > 0) //we need the latter to avoid self-occlusion weirdness               
                    {                       
                        float3 uvz = (min(max(mip - 2, 0), 4) + float3(0, 5, 10) + 0.5) / 15.0;    
                        float4 shr = tex3Dlod(sNEWGI_SHVolume, float4(tap_uv, uvz.x, 0));
                        float4 shg = tex3Dlod(sNEWGI_SHVolume, float4(tap_uv, uvz.y, 0));
                        float4 shb = tex3Dlod(sNEWGI_SHVolume, float4(tap_uv, uvz.z, 0));  
                        
                        float2 bits = countbits(changed_bits);
                        float hit = (bits.x + bits.y) / 64.0;

                        slice_result += float4(max(4 * SphericalHarmonics::linear_eval_irradiance(shr, shg, shb, -L1, 2), 0) * (iL1L1 * hit), hit); //matched against ZH3
                    }                                                                  
                }          
            }
     
            scaled_dir = -scaled_dir;
            initial_step = -initial_step;
        }

        slice_result *= sliceweight; //apply it here outside the inner loop
        slice_result.w = 1 - slice_result.w; //works better for the importance sampling
     
        float target_pdf = dot(slice_result.rgb, float3(0.2125, 0.7126, 0.0722));  

        //sacrifice a little IL importance sampling strength for AO if its intensity is high
        target_pdf += slice_result.w * 0.01 * saturate(RT_AO_AMOUNT * 0.1) * saturate(1 - RT_AMBIENT_LEVEL); 

        target_pdf = 1;   

        //target_pdf = TURN_ON_THE_MAGIC ? target_pdf : 1.0; 
        atomicAdd(tgsm_pdf_accum[idx],          uint(target_pdf / pdf * (1.0 - relative_pos_in_bracket) * FLOAT_TO_UINT_QUANTIZATION_SCALE));
        atomicAdd(tgsm_pdf_accum[idx_next_bin], uint(target_pdf / pdf *        relative_pos_in_bracket  * FLOAT_TO_UINT_QUANTIZATION_SCALE));      
        result += slice_result / (pdf * NUM_DIRECTIONS + 1e-4);                 
    }
   
    result /= num_slices;
    return result;
}

void TraceWrapCubicCS(in CSIN i)
{    
    int num_blocks = 32 / TILE_DIMENSIONS;
 
    //these are for the builder threads only, for writing the CDF we use the ids based off the shuffled pixels
    int id_in_block = i.threadid % NUM_DIRECTIONS;
    int block_start = i.threadid - id_in_block;
    int block_end   = block_start + (NUM_DIRECTIONS - 1);
    int2 pdf_storage_pos = i.groupid.xy * 32 + int2(i.threadid % 32, i.threadid / 32);

    float prev_pdf = tex2Dfetch(stNEWGI_STSGCache, pdf_storage_pos).x;
    tgsm_pdf_accum[i.threadid] = 0;   
    tgsm_pdf[i.threadid] = prev_pdf + 0.005; //choke, do not change  
    barrier();

    //init cubic prefix sum nodes, then perform sklansky style prefix sum
    if(id_in_block == 0)
        tgsm_cdf[i.threadid] = 0;
    else 
        tgsm_cdf[i.threadid] = (tgsm_pdf[i.threadid - 1] + tgsm_pdf[i.threadid]) * 0.5;
    
    barrier();
        
    [unroll]
    for(uint b = 1, m = 0; b < NUM_DIRECTIONS; barrier())
    {
        uint b2 = b * 2; uint m2 = b2 - 1; 
        if(i.threadid & b)       
            tgsm_cdf[i.threadid] += tgsm_cdf[(i.threadid & ~m2) + m];
        b = b2, m = m2;              
    }
    
    //normalize both PDF and CDF
    //the exclusive prefix sum for cubic interpolation is missing 0.5x the first and last entry
    float pdf_integral = tgsm_cdf[block_end]
                       + 0.5 * tgsm_pdf[block_start]
                       + 0.5 * tgsm_pdf[block_end];    
    barrier(); 
    tgsm_pdf[i.threadid] /= pdf_integral;
    tgsm_cdf[i.threadid] /= pdf_integral;   
    barrier();

    //actually perform the GI trace
    TraceContext ctx = _TraceContext(i, BUFFER_SCREEN_SIZE_DLSS);

    float4 gi = 0.0;
    if(check_boundaries(ctx.texel, BUFFER_SCREEN_SIZE_DLSS))     
        gi = trace_diffuse_cdf_cubic(ctx);     
    int2 write_id = ctx.texel & 31u;
    int write_thread = write_id.x + write_id.y * 32;

    tgsm_cdf[write_thread] = gi.x;barrier();gi.x = tgsm_cdf[i.threadid];barrier();   
    tgsm_cdf[write_thread] = gi.y;barrier();gi.y = tgsm_cdf[i.threadid];barrier(); 
    tgsm_cdf[write_thread] = gi.z;barrier();gi.z = tgsm_cdf[i.threadid];barrier(); 
    tgsm_cdf[write_thread] = gi.w;barrier();gi.w = tgsm_cdf[i.threadid];barrier(); 

    //filtering happens in YCoCg
    gi.rgb = linear_to_ycocg(gi.rgb);
    tex2Dstore(stNEWGI_Aux0, i.dispatchthreadid.xy, gi);
    barrier();

    //read back the collected PDF values of current frame and normalize
    float curr_pdf = float(tgsm_pdf_accum[i.threadid]) / FLOAT_TO_UINT_QUANTIZATION_SCALE;
    tgsm_pdf[i.threadid] = curr_pdf;
    barrier();
    
    [unroll]for(int stride = NUM_DIRECTIONS / 2; stride > 0; stride >>= 1)
    {
        if(id_in_block < stride)
            tgsm_pdf[i.threadid] += tgsm_pdf[i.threadid + stride];
        barrier();
    }

    curr_pdf /= tgsm_pdf[block_start] + 1e-8; 

    //output interpolated PDF
    float integrated_pdf = lerp(prev_pdf, curr_pdf, 0.25);
    tex2Dstore(stNEWGI_STSGCache, pdf_storage_pos, integrated_pdf);    
}

/*=============================================================================
	Temporal Reprojection    
=============================================================================*/

groupshared float4 moments_tgsm[16 * 16];

//2x2 downsample and gaussian blur
//+- 5 gaussian blur ~ 5x5 gaussian blur on halfres data
//8x8 group that does tiled can reach a 16x16 area
void SpatialMomentsCS(CSIN i)
{
    [unroll]for(int y = 0; y < 2; ++y)
    [unroll]for(int x = 0; x < 2; ++x) 
    {
        //process 2x2 blocks, each 8x8 sized, centered on the current 8x8 group
        int2 p = i.groupid.xy * 8 + i.groupthreadid.xy + uint2(x, y) * 8 - 4;
        //we're in halfres, so let's go fullres
        //gather needs a +0.5 offset, and we also need an offset of +0.5 to to shift to quad centers
        float2 gather_uv = (p * 2 + 1) * BUFFER_PIXEL_SIZE_DLSS;

        float4 m1_curr = tex2DgatherR(sNEWGI_Aux0,      gather_uv);
        float4 m1_prev = tex2DgatherR(sNEWGI_AccumDiff, gather_uv); 
        //average in quad 
        float4 m;
        m.x = dot(0.25, m1_curr);
        m.y = dot(0.25, m1_curr * m1_curr);  
        m.z = dot(0.25, m1_prev);
        m.w = dot(0.25, m1_prev * m1_prev);
        int2 tgsm_pos = i.groupthreadid.xy + int2(x, y) * 8;
        moments_tgsm[tgsm_pos.y * 16 + tgsm_pos.x] = m;
    }
    barrier();

    //7x7 gaussian blur in smem
    float4 res = 0;
    float wsum = 0;
    [unroll]for(int x = -3; x <= 3; ++x)
    [unroll]for(int y = -3; y <= 3; ++y)
    {
        int2 tgsm_pos = i.groupthreadid.xy + 4 + int2(x, y);
        float w = exp(-(x*x+y*y) / 9.0 * 0.5 * 4);
        res += moments_tgsm[tgsm_pos.y * 16 + tgsm_pos.x] * w;
        wsum += w;
    }
    res /= wsum; 

    //we output mean | variance | mean | variance
    //             CURR       |       PREV
    res.yw = sqrt(max(0, res.yw - res.xz * res.xz));  
    tex2Dstore(stNEWGI_SpatialMoments, i.dispatchthreadid.xy, res);   
}

float lanczos2( float x )
{ 		
    float t = saturate(x * x * 0.25);//mul, mul_sat
    float res = 1 - 4.0/9.0 * t;//mad
    res = res - res * t;//mad
    res *= res;//mul
    res = res - res * t; //mad
    res *= 1 - 4 * t;//mad, mul
    return res;
}

float decode_temporal_variance(float v)
{    
    v *= v;  
    v /= VARIANCE_FP16_QUANTIZATION_SCALE;
    return v;
}

float encode_temporal_variance(float v)
{
    v *= VARIANCE_FP16_QUANTIZATION_SCALE;           
    v = sqrt(v);   
    return v;
}

void TemporalReprojectionPS(in VSOUT i, out PSOUT2 o)
{
    float2 prev_uv = i.uv + Deferred::get_motion(i.uv);
    //prev_uv = i.uv + float2(1, 1) * BUFFER_PIXEL_SIZE_DLSS;
    bool inside_screen = Math::inside_screen(prev_uv); 
    bool valid_history = inside_screen;

    float3 n = Deferred::get_normals(i.uv);
    float3 p = Camera::uv_to_proj(i.uv);    
    float  z = p.z;
    
    float NdotV = dot(p, n) * rsqrt(dot(p, p));
    float4 prev_diff = tex2D(sNEWGI_AccumDiff, prev_uv); //YCoCg AO

    float prev_variance = 0;
    float history_confidence = 0;

    [branch]
    if(inside_screen)
    {       
        //16x fetch gbuffer -> 4x gather for depth, 2x gather for normals, 1x gather for variance 
        float2 texel_uv = prev_uv * BUFFER_SCREEN_SIZE_DLSS - 0.5;
        int2 texel_lower = floor(texel_uv);
        float2 bilinear_kernel = frac(texel_uv);
        float4 bilinX = float4(0, 1 - frac(texel_uv.x), frac(texel_uv.x), 0);
        float4 bilinY = float4(0, 1 - frac(texel_uv.y), frac(texel_uv.y), 0); 

        float4 bilinear_weights; 
        bilinear_weights.x = (1 - bilinear_kernel.x) * (1 - bilinear_kernel.y);
        bilinear_weights.y =      bilinear_kernel.x  * (1 - bilinear_kernel.y);
        bilinear_weights.z = (1 - bilinear_kernel.x) *      bilinear_kernel.y;
        bilinear_weights.w =      bilinear_kernel.x  *      bilinear_kernel.y;
        float4 quad_anchors = float4(texel_lower.xyxy + float4(0, 0, 2, 2)) * BUFFER_PIXEL_SIZE_DLSS.xyxy;

        //first, gather depth in 4 quadrants
        float4 quad_z_00 = tex2DgatherR(sNEWGI_PrevTemporalData, quad_anchors.xy).wzxy;  //XY|XY
        float4 quad_z_10 = tex2DgatherR(sNEWGI_PrevTemporalData, quad_anchors.zy).wzxy;  //ZW|ZW   inner:   XY
        float4 quad_z_01 = tex2DgatherR(sNEWGI_PrevTemporalData, quad_anchors.xw).wzxy;  //XY|XY            ZW
        float4 quad_z_11 = tex2DgatherR(sNEWGI_PrevTemporalData, quad_anchors.zw).wzxy;  //ZW|ZW

        //-128 * abs(quad_z_00 - z) / z * abs(NdotV)
        //-128 * abs(quad_z_00 / z - z / z) * abs(NdotV)
        //-128 * abs(quad_z_00 / z - 1) * abs(NdotV)
        //-128 * abs(quad_z_00 / z * abs(NdotV) - abs(NdotV))
        //-abs(quad_z_00 / z * abs(NdotV) * 128 - abs(NdotV) * 128)
        float2 scalemad = float2(rcp(z), -1) * abs(NdotV) * 128;
        float4 reject_00 = exp2(-abs(quad_z_00 * scalemad.x + scalemad.y));
        float4 reject_10 = exp2(-abs(quad_z_10 * scalemad.x + scalemad.y));
        float4 reject_01 = exp2(-abs(quad_z_01 * scalemad.x + scalemad.y));
        float4 reject_11 = exp2(-abs(quad_z_11 * scalemad.x + scalemad.y));

        float4 octnx = tex2DgatherG(sNEWGI_PrevTemporalData, lerp(quad_anchors.xy, quad_anchors.zw, 0.5)).wzxy;
        float4 octny = tex2DgatherB(sNEWGI_PrevTemporalData, lerp(quad_anchors.xy, quad_anchors.zw, 0.5)).wzxy;
        //first, use normals and depth weight in 2x2 center
        float4 centerweights_z = float4(reject_00.w, reject_10.z, reject_01.y, reject_11.x);
        float4 centerweights_n;
        centerweights_n.x = saturate(dot(Math::octahedral_dec(float2(octnx.x, octny.x)), n));
        centerweights_n.y = saturate(dot(Math::octahedral_dec(float2(octnx.y, octny.y)), n));
        centerweights_n.z = saturate(dot(Math::octahedral_dec(float2(octnx.z, octny.z)), n));
        centerweights_n.w = saturate(dot(Math::octahedral_dec(float2(octnx.w, octny.w)), n));
     
        float4 lanczosX, lanczosY;       
        lanczosX.x = lanczos2(-bilinear_kernel.x - 1);  
        lanczosX.y = lanczos2(-bilinear_kernel.x    ); 
        lanczosX.z = lanczos2(-bilinear_kernel.x + 1); 
        lanczosX.w = lanczos2(-bilinear_kernel.x + 2); 
        lanczosY.x = lanczos2(-bilinear_kernel.y - 1);  
        lanczosY.y = lanczos2(-bilinear_kernel.y    ); 
        lanczosY.z = lanczos2(-bilinear_kernel.y + 1); 
        lanczosY.w = lanczos2(-bilinear_kernel.y + 2);
        //accumulate bilinear (and lanczos) in center
        float4 gi_00_center = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(0, 0));
        float4 gi_10_center = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(1, 0));
        float4 gi_01_center = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(0, 1));
        float4 gi_11_center = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(1, 1)); 
        //bilinear, z and normal
        float4 bilinear_combined_weights = bilinear_weights * centerweights_z * centerweights_n;
        float4 mean_bilinear = 0;
        mean_bilinear += gi_00_center * bilinear_combined_weights.x;
        mean_bilinear += gi_10_center * bilinear_combined_weights.y;
        mean_bilinear += gi_01_center * bilinear_combined_weights.z;
        mean_bilinear += gi_11_center * bilinear_combined_weights.w;
        //lanczos, only z
        float4 mean_lanczos = 0; 
        float4 lanczos_combined_weights = lanczosX.yzyz * lanczosY.yyzz * centerweights_z;
        mean_lanczos += gi_00_center * lanczos_combined_weights.x;
        mean_lanczos += gi_10_center * lanczos_combined_weights.y;
        mean_lanczos += gi_01_center * lanczos_combined_weights.z;
        mean_lanczos += gi_11_center * lanczos_combined_weights.w;
                
        float4 variances = tex2DgatherA(sNEWGI_PrevTemporalData, lerp(quad_anchors.xy, quad_anchors.zw, 0.5)).wzxy;
        variances.x = decode_temporal_variance(variances.x);
        variances.y = decode_temporal_variance(variances.y);
        variances.z = decode_temporal_variance(variances.z);
        variances.w = decode_temporal_variance(variances.w);
        prev_variance = dot(bilinear_combined_weights, variances); 

        //also track minmax
        float4 minv = min(min(gi_00_center, gi_10_center), min(gi_01_center, gi_11_center));
        float4 maxv = max(max(gi_00_center, gi_10_center), max(gi_01_center, gi_11_center));
        //then add the other lanczos taps 
        float4 tapA, tapB;
        //2 leftleft
        float2 weights_lanczos_ll = lanczosX.xx * lanczosY.yz * float2(reject_00.z, reject_01.x);
        tapA = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(-1, 0));
        tapB = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(-1, 1));
        mean_lanczos += tapA * weights_lanczos_ll.x;
        mean_lanczos += tapB * weights_lanczos_ll.y;
        maxv = max(maxv, max(tapA, tapB));
        minv = min(minv, min(tapA, tapB));
        //2 rightright
        float2 weights_lanczos_rr = lanczosX.ww * lanczosY.yz * float2(reject_10.w, reject_11.y);
        tapA = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(2, 0));
        tapB = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(2, 1));
        mean_lanczos += tapA * weights_lanczos_rr.x;
        mean_lanczos += tapB * weights_lanczos_rr.y;
        maxv = max(maxv, max(tapA, tapB));
        minv = min(minv, min(tapA, tapB));
        //2 toptop
        float2 weights_lanczos_tt = lanczosX.yz * lanczosY.xx * float2(reject_00.y, reject_10.x);
        tapA = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(0, -1));
        tapB = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(1, -1));
        mean_lanczos += tapA * weights_lanczos_tt.x;
        mean_lanczos += tapB * weights_lanczos_tt.y;
        maxv = max(maxv, max(tapA, tapB));
        minv = min(minv, min(tapA, tapB));
        //2 bottombottom
        float2 weights_lanczos_bb = lanczosX.yz * lanczosY.ww * float2(reject_01.w, reject_11.z);
        tapA = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(0, 2));
        tapB = tex2Dfetch(sNEWGI_AccumDiff, texel_lower + int2(1, 2));
        mean_lanczos += tapA * weights_lanczos_bb.x;
        mean_lanczos += tapB * weights_lanczos_bb.y;
        maxv = max(maxv, max(tapA, tapB));
        minv = min(minv, min(tapA, tapB));

        float wsum_bilinear = dot(bilinear_combined_weights, 1);
        float wsum_lanczos = dot(lanczos_combined_weights, 1) + dot(weights_lanczos_ll + weights_lanczos_rr + weights_lanczos_tt + weights_lanczos_bb, 1);

        prev_variance /= wsum_bilinear + 1e-6;
        mean_bilinear /= wsum_bilinear + 1e-6;
        mean_lanczos /= (abs(wsum_lanczos) + 1e-6) * (wsum_lanczos >= 0 ? 1 : -1);

        prev_diff = lerp(mean_bilinear, mean_lanczos, saturate(wsum_bilinear * 4));
        prev_diff = clamp(prev_diff, minv, maxv); 

        if(wsum_bilinear < 0.05)
        {
            valid_history = false;
        }  

        history_confidence = wsum_bilinear;  
    }   

    float2 curr_data = tex2D(sNEWGI_SpatialMoments,    i.uv).xy;
    float2 prev_data = tex2D(sNEWGI_SpatialMoments, prev_uv).zw;

    float bias = abs(curr_data.x - prev_data.x);
    float var_x = prev_data.y * prev_data.y;
    float var_y = curr_data.y * curr_data.y;
    float denom = exp2(-32.0) + var_x + var_y + bias * bias;    
    float alpha = saturate(1.0 - var_y / denom);
    alpha = clamp(alpha, 0.01, 0.15);

    float4 curr_diff = tex2D(sNEWGI_Aux0, i.uv);

    float X = prev_diff.x;
    float Y = curr_diff.x; 
    float variance_update = (X - Y) * (lerp(X, Y, alpha) - Y);   

    if(!valid_history)
    {
        variance_update = var_y * 16.0; //substitute a sensible high value that'll cause lots of blur
        alpha = 1;
    } 

    variance_update *= alpha * 0.5; //make it equivalent to spatial variance    
    float temporal_variance = lerp(prev_variance, variance_update, alpha);

    bool early_out = can_earlyout(Camera::z_to_depth(p.z));

    o.t0 = lerp(prev_diff, curr_diff, alpha); 
    //z negative -> can early out, easier to store than to do it in every filter pass. abs() on inputs is free.   
    o.t1 = float4(early_out ? -p.z : p.z, Math::octahedral_enc(n), encode_temporal_variance(temporal_variance)); 
}

void UpdateHistoryCS(in CSIN i)
{    
    const int groupsize = 8;
    int2 p = i.groupid.xy * groupsize * 2 + SFC::morton_i_to_xy(i.threadid).yx;
    int2 p00 = p;
    int2 p01 = int2(p.x + groupsize, p.y);
    int2 p10 = int2(p.x, p.y + groupsize);
    int2 p11 = int2(p.x + groupsize, p.y + groupsize);
    //no storages as function parameters means copypaste goes brr
    {
        float4 t00 = tex2Dfetch(sNEWGI_Aux1, p00);
        float4 t01 = tex2Dfetch(sNEWGI_Aux1, p01);
        float4 t10 = tex2Dfetch(sNEWGI_Aux1, p10);
        float4 t11 = tex2Dfetch(sNEWGI_Aux1, p11);

        tex2Dstore(stNEWGI_AccumDiff, p00, t00);
        tex2Dstore(stNEWGI_AccumDiff, p01, t01);
        tex2Dstore(stNEWGI_AccumDiff, p10, t10);
        tex2Dstore(stNEWGI_AccumDiff, p11, t11);
    }
    {
        float4 t00 = tex2Dfetch(sNEWGI_Aux3, p00);
        float4 t01 = tex2Dfetch(sNEWGI_Aux3, p01);
        float4 t10 = tex2Dfetch(sNEWGI_Aux3, p10);
        float4 t11 = tex2Dfetch(sNEWGI_Aux3, p11);

        tex2Dstore(stNEWGI_PrevTemporalData, p00, t00);
        tex2Dstore(stNEWGI_PrevTemporalData, p01, t01);
        tex2Dstore(stNEWGI_PrevTemporalData, p10, t10);
        tex2Dstore(stNEWGI_PrevTemporalData, p11, t11);
    }
}

/*=============================================================================
	Denoise
=============================================================================*/

float get_signal_weight(float m1, float m2, float v1, float v2, float sharpness)
{
    float a = rsqrt(v1 + v1);
    float bias = (m1 - m2) * a;
    return sqrt(v1) * a * exp(-(0.5 * sharpness) * bias * bias) * 1.414;   
}

void atrous_pass(in int2 center_texel, 
                 sampler s_diff,
                 sampler s_gbuf,
                 const int it,
                 out PSOUT2 filter_out)
{
    if(it > (DENOISER_Q * 2 + 1)) discard; //0->1    1->3   2->5

    int scale = (DENOISER_Q ? 1 : 2) << it;
    int2 offsets[8] = 
    {
        int2(-1, -1) * scale, int2(0, -1) * scale, int2(1, -1) * scale,
        int2(-1,  0) * scale,                      int2(1,  0) * scale,
        int2(-1,  1) * scale, int2(0,  1) * scale, int2(1,  1) * scale
    };

    float2 center_uv = pixel_idx_to_uv(center_texel, BUFFER_SCREEN_SIZE_DLSS);
    float4 center_gbuf = tex2Dfetch(s_gbuf, center_texel);
    float4 center_diff = tex2Dfetch(s_diff, center_texel);

    filter_out.t0 = center_diff;
    filter_out.t1 = center_gbuf;

    bool early_out = center_gbuf.x < 0;
    if(early_out)
    {
        filter_out.t0 = float4(0, 0, 0, 1); //AO inverted.
        return;
    }

    float3 center_pos       = Camera::uv_to_proj(center_uv, abs(center_gbuf.x));//undo sign flag
    float3 center_normal    = Math::octahedral_dec(center_gbuf.yz);
    float3 center_geonormal = Deferred::get_geometry_normals(center_uv);
    float  center_var       = decode_temporal_variance(center_gbuf.w); 

    float variances[8];
    float weights[8];

    [unroll]
    for(int j = 0; j < 8; j++)
    {        
        float4 gbuf = tex2Dfetch(s_gbuf, center_texel + offsets[j]);

        float  tap_z = abs(gbuf.x); //undo sign flag
        float3 tap_n = Math::octahedral_dec(gbuf.yz);
        float  tap_v = gbuf.w;        
  
        float2 uv = pixel_idx_to_uv(center_texel + offsets[j], BUFFER_SCREEN_SIZE_DLSS);
        float3 deltav = Camera::uv_to_proj(uv, tap_z) - center_pos;
        float plane_dist = abs(dot(deltav, center_geonormal));
        float eucli_dist = length(deltav);
        float dist = lerp(plane_dist, eucli_dist, 0.25) / center_pos.z;

        float wz = dist * 100.0;
        wz = exp2(-wz * wz); 
 
        float wn = saturate(exp((dot(tap_n, center_normal) - 1) * 64.0));
      
        weights[j]   = lerp(0.001, 1, saturate(wz * wn));
        variances[j] = decode_temporal_variance(tap_v);
    }   

    float sharpness = saturate(1 - sqrt(FILTER_SMOOTHNESS) * 0.98);
    sharpness *= sharpness;
    
    float wsum = 1;
    filter_out.t0 = 0;
    filter_out.t1 = float4(center_gbuf.xyz, center_var);

    float4 minv = 1e10;
    float4 maxv = -1e10;

    [loop]
    for(int j = 0; j < 8; j++)
    {
        int2 texel = center_texel + offsets[j];
        if(any(texel < 0) || any(texel >= BUFFER_SCREEN_SIZE_DLSS)) continue;

        float4 tap_diff = tex2Dfetch(s_diff, texel);        
        float w = weights[j] * get_signal_weight(center_diff.x, 
                               tap_diff.x, 
                               exp2(-32.0) + center_var, 
                               exp2(-32.0) + variances[j], sharpness);       
        wsum += w;
        filter_out.t0   += tap_diff     * w;
        filter_out.t1.w += variances[j] * w * w;       

        minv = min(minv, tap_diff);
        maxv = max(maxv, tap_diff);
    }

    [flatten]
    if(it < 0.5)
    {
        center_diff = clamp(center_diff, minv, maxv);
    }

    filter_out.t0 += center_diff;   
    filter_out.t0   /= wsum;
    filter_out.t1.w /= wsum * wsum;  //schied et al 2017     
    filter_out.t1.w = encode_temporal_variance(filter_out.t1.w);

    //last iteration postamble. 
    //Could be done in the blend pass but it requires depth, and thus is ill-suited
    //for TAAU, hence we do it here.
    [branch]
    if(it == (DENOISER_Q * 2 + 1))
    {  
        //apply fade and overall scaling here. No ambient yet since that is constant for every pixel.
        float fade = 1 - get_fade_factor(Camera::z_to_depth(center_pos.z));
        float rtao = saturate(filter_out.t0.w);
        rtao = lerp(1, rtao, saturate(RT_AO_AMOUNT * 0.1)) * saturate(RT_AMBIENT_LEVEL);
        rtao = lerp(rtao, 1, fade);        

        float3 diff_gi = filter_out.t0.rgb;
        diff_gi *= RT_IL_AMOUNT * RT_IL_AMOUNT * 2;
        diff_gi = lerp(diff_gi, 0, fade);
        filter_out.t0 = float4(diff_gi, rtao);
    }
}

void DenoisePS0(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux1, sNEWGI_Aux3, 0, o);}
void DenoisePS1(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux0, sNEWGI_Aux2, 1, o);}
void DenoisePS2(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux1, sNEWGI_Aux3, 2, o);}
void DenoisePS3(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux0, sNEWGI_Aux2, 3, o);}
void DenoisePS4(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux1, sNEWGI_Aux3, 4, o);}
void DenoisePS5(in VSOUT i, out PSOUT2 o){atrous_pass(i.vpos.xy, sNEWGI_Aux0, sNEWGI_Aux2, 5, o);}

/*=============================================================================
	TAAU Compatibility Layer
=============================================================================*/

#ifdef _MARTYSMODS_TAAU_SCALE

texture NEWGI_TAAU_DiffuseBeta   { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
texture NEWGI_TAAU_DiffuseCov    { Width = BUFFER_WIDTH_DLSS; Height = BUFFER_HEIGHT_DLSS; Format = RGBA16F; };
sampler sNEWGI_TAAU_DiffuseBeta  { Texture = NEWGI_TAAU_DiffuseBeta; };
sampler sNEWGI_TAAU_DiffuseCov   { Texture = NEWGI_TAAU_DiffuseCov; };
storage stNEWGI_TAAU_DiffuseBeta  { Texture = NEWGI_TAAU_DiffuseBeta; };
storage stNEWGI_TAAU_DiffuseCov   { Texture = NEWGI_TAAU_DiffuseCov; };

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
    taau_resolve(i, sNEWGI_TAAU_DiffuseBeta, sNEWGI_TAAU_DiffuseCov, sNEWGI_Aux1, o.t0, o.t1);        
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
        float4 t00 = tex2Dfetch(sNEWGI_Aux0, p00);
        float4 t01 = tex2Dfetch(sNEWGI_Aux0, p01);
        float4 t10 = tex2Dfetch(sNEWGI_Aux0, p10);
        float4 t11 = tex2Dfetch(sNEWGI_Aux0, p11);

        tex2Dstore(stNEWGI_TAAU_DiffuseBeta, p00, t00);
        tex2Dstore(stNEWGI_TAAU_DiffuseBeta, p01, t01);
        tex2Dstore(stNEWGI_TAAU_DiffuseBeta, p10, t10);
        tex2Dstore(stNEWGI_TAAU_DiffuseBeta, p11, t11);
    }
    {
        float4 t00 = tex2Dfetch(sNEWGI_Aux2, p00);
        float4 t01 = tex2Dfetch(sNEWGI_Aux2, p01);
        float4 t10 = tex2Dfetch(sNEWGI_Aux2, p10);
        float4 t11 = tex2Dfetch(sNEWGI_Aux2, p11);

        tex2Dstore(stNEWGI_TAAU_DiffuseCov, p00, t00);
        tex2Dstore(stNEWGI_TAAU_DiffuseCov, p01, t01);
        tex2Dstore(stNEWGI_TAAU_DiffuseCov, p10, t10);
        tex2Dstore(stNEWGI_TAAU_DiffuseCov, p11, t11);
    }    
}

#endif 

/*=============================================================================
	Blend and Out
=============================================================================*/


void OutPS(in VSOUT i, out float3 o : SV_Target0)
{
#ifdef _MARTYSMODS_TAAU_SCALE
    float4 diff = tex2D(sNEWGI_Aux0, i.uv);
#else
    float4 diff = tex2D(sNEWGI_Aux1, i.uv);
#endif
    float3 rtgi = max(0, ycocg_to_linear(diff.rgb));
    float rtao  = diff.w;

    float3 albedo = Deferred::get_albedo(i.uv);
    float3 color = unpack_hdr(tex2D(ColorInput, i.uv).rgb); 

    if(RT_DEBUG_VIEW == 1)
    {
        color = albedo = 0.4444;
    }
  
    o = color * rtao + rtgi * albedo;  
    o = pack_hdr(o);

    if(RT_DEBUG_VIEW == 2)
    {
        float2 scaled_uv = i.uv * 5.0;
        int2 layer = int2(scaled_uv);
        scaled_uv = frac(scaled_uv);

        if(layer.x == 0)
        {    
#ifdef _MARTYSMODS_TAAU_SCALE
            float3 tiled_diff = max(0, ycocg_to_linear(tex2Dlod(sNEWGI_Aux0, scaled_uv, 0).rgb));
#else 
            float3 tiled_diff = max(0, ycocg_to_linear(tex2Dlod(sNEWGI_Aux1, scaled_uv, 0).rgb));
#endif
            float3 tiled_color = unpack_hdr(tex2Dlod(ColorInput, scaled_uv, 0).rgb);

            o = layer.y == 0 ? Debug::viridis(Depth::get_linear_depth(scaled_uv)) 
            : layer.y == 1 ? pack_hdr(tiled_diff)
            : layer.y == 2 ? Deferred::get_normals(scaled_uv) * 0.5 * float3(1,-1,-1) + 0.5
            : layer.y == 3 ? showmotion(Deferred::get_motion(scaled_uv))
            : layer.y == 4 ? Deferred::get_albedo(scaled_uv)
            : o;
        }
    }
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_NEWGI_Diffuse
<
    ui_label = "iMMERSE Pro: RTGI (Diffuse)";
    ui_tooltip =        
        "                         MartysMods - RTGI (Diffuse)                              \n"
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
        "Version: D-1.1";
>
{ 
    pass { ComputeShader = DownsampleDepthCS<16, 16>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS,  16*2); DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS,  16*2); GenerateMipMaps = false;}   
    pass { ComputeShader = InitRadianceVolumeCS<8, 8>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4,  8); DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/4, 8); GenerateMipMaps = false;} 
    pass { ComputeShader = PropagateRadianceCS0<16, 16>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4, 16); DispatchSizeY = CEIL_DIV((BUFFER_HEIGHT_DLSS/4), 16); GenerateMipMaps = false;} 
    pass { ComputeShader = PropagateRadianceCS1<16, 16>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4, 16); DispatchSizeY = CEIL_DIV((BUFFER_HEIGHT_DLSS/4), 16); GenerateMipMaps = false;} 
    pass { ComputeShader = PropagateRadianceCS2<16, 16>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4, 16); DispatchSizeY = CEIL_DIV((BUFFER_HEIGHT_DLSS/4), 16); GenerateMipMaps = false;} 
    pass { ComputeShader = PropagateRadianceCS3<16, 16>; DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/4, 16); DispatchSizeY = CEIL_DIV((BUFFER_HEIGHT_DLSS/4), 16); GenerateMipMaps = false;} 
    pass { ComputeShader = TraceWrapCubicCS<32, 32>;DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS, 32);DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS, 32); }
    pass { ComputeShader = SpatialMomentsCS<8, 8>;DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/2, 8);DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/2, 8); }
    pass { VertexShader = MainVS; PixelShader = TemporalReprojectionPS; RenderTarget0 = NEWGI_Aux1;  RenderTarget1 = NEWGI_Aux3;}
    pass { ComputeShader = UpdateHistoryCS<8, 8>;DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/2, 8);DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/2, 8); }
    pass { VertexShader = MainVS; PixelShader = DenoisePS0; RenderTarget0 = NEWGI_Aux0; RenderTarget1 = NEWGI_Aux2; GenerateMipMaps = false;}     
    pass { VertexShader = MainVS; PixelShader = DenoisePS1; RenderTarget0 = NEWGI_Aux1; RenderTarget1 = NEWGI_Aux3; GenerateMipMaps = false;}  
    pass { VertexShader = MainVS; PixelShader = DenoisePS2; RenderTarget0 = NEWGI_Aux0; RenderTarget1 = NEWGI_Aux2; GenerateMipMaps = false;}          
    pass { VertexShader = MainVS; PixelShader = DenoisePS3; RenderTarget0 = NEWGI_Aux1; RenderTarget1 = NEWGI_Aux3; GenerateMipMaps = false;}
    pass { VertexShader = MainVS; PixelShader = DenoisePS4; RenderTarget0 = NEWGI_Aux0; RenderTarget1 = NEWGI_Aux2; GenerateMipMaps = false;}
    pass { VertexShader = MainVS; PixelShader = DenoisePS5; RenderTarget0 = NEWGI_Aux1; RenderTarget1 = NEWGI_Aux3; GenerateMipMaps = false;}   

#ifdef _MARTYSMODS_TAAU_SCALE
    pass { VertexShader = MainVS; PixelShader = TAAUResolvePS;       RenderTarget0 = NEWGI_Aux0; RenderTarget1 = NEWGI_Aux2;  }
    pass { ComputeShader = TAAUUpdateHistoryCS<8, 8>;DispatchSizeX = CEIL_DIV(BUFFER_WIDTH_DLSS/2, 8);DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT_DLSS/2, 8); }
#endif //_MARTYSMODS_TAAU_SCALE   
   
    pass { VertexShader = MainVS; PixelShader = OutPS; }
}





