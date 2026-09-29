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

    ReLight 0.5

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/


/*=============================================================================
	Preprocessor settings
=============================================================================*/

#ifndef AMOUNT_OF_LIGHTS
 #define AMOUNT_OF_LIGHTS 2
#endif

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform float AMBIENT_INT <
	ui_type = "drag";
    ui_label = "Ambient Intensity";
    ui_category = "Global";
	ui_min = 0.0; ui_max = 1.0;
> = 1.0;

uniform int SHADOW_MODE <
    ui_type = "combo";
    ui_label = "Shadow Tracing";
	ui_items = "Off\0Visibility Test\0Recursive Path Tracing\0";
    ui_category = "Global";
> = 1;

uniform int SHADOW_Q <
	ui_type = "combo";
    ui_label = "Shadow Trace Quality";
	ui_items = "Low\0Medium\0High\0Ultra\0Maximum\0";
    ui_category = "Global";
> = 1;

uniform float SHADOWS_OBJ_THICKNESS <
	ui_type = "drag";
    ui_label = "Object Thickness";
	ui_min = 0.0; ui_max = 10.0;
    ui_category = "Global";
> = 4.0;

uniform bool USE_SSS <
    ui_label = "Enable Subsurface Scattering";
    ui_category = "Subsurface Scattering (SSS)";
> = false;

uniform int SSS_Q <
	ui_type = "combo";
    ui_label = "Quality";
	ui_items = "Very Low\0Low\0Medium\0High\0";
    ui_category = "Subsurface Scattering (SSS)";
> = 1;

uniform float SSS_SAT <
    ui_type = "drag";
    ui_min = 0.0; ui_max = 1.0;
    ui_label = "Saturation";
    ui_category = "Subsurface Scattering (SSS)";
> = 0.7;

uniform float SSS_RAD <
    ui_type = "drag";
    ui_min = 0.0; ui_max = 1.0;
    ui_label = "Scattering Radius";
    ui_category = "Subsurface Scattering (SSS)";
> = 0.5;

uniform float SSS_HUE_MASK_CENTER <
    ui_type = "drag";
    ui_min = 0.0; ui_max = 360.0;
    ui_step = 1.0;
    ui_label = "Skin Hue";
    ui_category = "Subsurface Scattering (SSS)";
> = 18.0;

uniform float SSS_HUE_MASK_RANGE <
    ui_type = "drag";
    ui_min = 0.0; ui_max = 1.0;
    ui_label = "SSS Skin Hue Tolerance";
    ui_category = "Subsurface Scattering (SSS)";
> = 0.1;

uniform bool   LIGHT0_ENABLE <ui_label = "Active";ui_category = "Light 1";> = true;
uniform int    LIGHT0_TYPE   <ui_type = "combo";ui_label = "Type";ui_items = "Sphere\0Infinite\0";ui_category = "Light 1";> = 0;
uniform float2 LIGHT0_TT     <ui_type = "drag";ui_min = -1.0; ui_max = 1.0; ui_label="Temp / Tint";ui_category = "Light 1";> = float2(0, 0);
uniform float  LIGHT0_INT    <ui_type = "drag";ui_label = "Intensity";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 1";> = 1.0;
uniform float  LIGHT0_PENUM  <ui_type = "drag";ui_label = "Penumbra";ui_min = 0.0; ui_max = 10.0;ui_category = "Light 1";> = 0.5;
uniform float2 LIGHT0_AZELE  <ui_type = "slider"; ui_label = "Infinite: Azimuth / Elevation"; ui_min = 0.0; ui_max = 1.0;ui_category = "Light 1";> = float2(0.314, 0.666);
uniform float3 LIGHT0_POS    <ui_type = "drag";ui_label = "Sphere: Position X Y Z";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 1";> = float3(0.314, 0.666, 0.314);

#if AMOUNT_OF_LIGHTS > 1
uniform bool   LIGHT1_ENABLE <ui_label = "Active";ui_category = "Light 2";> = true;
uniform int    LIGHT1_TYPE   <ui_type = "combo";ui_label = "Type";ui_items = "Sphere\0Infinite\0";ui_category = "Light 2";> = 0;
uniform float2 LIGHT1_TT     <ui_type = "drag";ui_min = -1.0; ui_max = 1.0; ui_label="Temp / Tint";ui_category = "Light 2";> = float2(0, 0);
uniform float  LIGHT1_INT    <ui_type = "drag";ui_label = "Intensity";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 2";> = 1.0;
uniform float  LIGHT1_PENUM  <ui_type = "drag";ui_label = "Penumbra";ui_min = 0.0; ui_max = 10.0;ui_category = "Light 2";> = 0.5;
uniform float2 LIGHT1_AZELE  <ui_type = "slider"; ui_label = "Infinite: Azimuth / Elevation"; ui_min = 0.0; ui_max = 1.0;ui_category = "Light 2";> = float2(0.314, 0.666);
uniform float3 LIGHT1_POS    <ui_type = "drag";ui_label = "Sphere: Position X Y Z";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 2";> = float3(0.314, 0.666, 0.314);
#endif
#if AMOUNT_OF_LIGHTS > 2
uniform bool   LIGHT2_ENABLE <ui_label = "Active";ui_category = "Light 3";> = true;
uniform int    LIGHT2_TYPE   <ui_type = "combo";ui_label = "Type";ui_items = "Sphere\0Infinite\0";ui_category = "Light 3";> = 0;
uniform float2 LIGHT2_TT     <ui_type = "drag";ui_min = -1.0; ui_max = 1.0; ui_label="Temp / Tint";ui_category = "Light 3";> = float2(0, 0);
uniform float  LIGHT2_INT    <ui_type = "drag";ui_label = "Intensity";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 3";> = 1.0;
uniform float  LIGHT2_PENUM  <ui_type = "drag";ui_label = "Penumbra";ui_min = 0.0; ui_max = 10.0;ui_category = "Light 3";> = 0.5;
uniform float2 LIGHT2_AZELE  <ui_type = "slider"; ui_label = "Infinite: Azimuth / Elevation"; ui_min = 0.0; ui_max = 1.0;ui_category = "Light 3";> = float2(0.314, 0.666);
uniform float3 LIGHT2_POS    <ui_type = "drag";ui_label = "Sphere: Position X Y Z";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 3";> = float3(0.314, 0.666, 0.314);
#endif
#if AMOUNT_OF_LIGHTS > 3
uniform bool   LIGHT3_ENABLE <ui_label = "Active";ui_category = "Light 4";> = true;
uniform int    LIGHT3_TYPE   <ui_type = "combo";ui_label = "Type";ui_items = "Sphere\0Infinite\0";ui_category = "Light 4";> = 0;
uniform float2 LIGHT3_TT     <ui_type = "drag";ui_min = -1.0; ui_max = 1.0; ui_label="Temp / Tint";ui_category = "Light 4";> = float2(0, 0);
uniform float  LIGHT3_INT    <ui_type = "drag";ui_label = "Intensity";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 4";> = 1.0;
uniform float  LIGHT3_PENUM  <ui_type = "drag";ui_label = "Penumbra";ui_min = 0.0; ui_max = 10.0;ui_category = "Light 4";> = 0.5;
uniform float2 LIGHT3_AZELE  <ui_type = "slider"; ui_label = "Infinite: Azimuth / Elevation"; ui_min = 0.0; ui_max = 1.0;ui_category = "Light 4";> = float2(0.314, 0.666);
uniform float3 LIGHT3_POS    <ui_type = "drag";ui_label = "Sphere: Position X Y Z";ui_min = 0.0; ui_max = 1.0;ui_category = "Light 4";> = float3(0.314, 0.666, 0.314);
#endif

uniform bool USE_ALBEDO_ESTIMATION <
    ui_label = "Use Albedo Estimation";
    ui_category = "Experimental";
    ui_tooltip = "Experimental estimation of surface albedo from the image.\n"
                 "This makes the light blending more correct, but since the albedo estimation\n"
                 "is not perfect, it can produce strange colors in some cases.";
> = false;

uniform int DEBUG_MODE <
	ui_type = "combo";
    ui_label = "Debug Outputs";
	ui_items = "None\0Validation Layer (all)\0Lighting\0SSS Skin Mask\0";
    ui_category = "Debug";
> = 0;

uniform int LIGHT_OVERLAY_BEHAVIOR <
	ui_type = "combo";
    ui_label = "Light Overlay";
	ui_items = "Disabled\0Show while GUI is open\0Show while GUI is open and on screenshots\0Show always\0";
    ui_category = "Debug";
> = 0;

uniform float LIGHT_OVERLAY_OPACITY <
    ui_type = "slider";
    ui_min = 0.1; ui_max = 1.0;
    ui_label = "Light Overlay Opacity";
    ui_category = "Debug";
> = 1.0;
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

uniform bool halt_frame_counter < > = false;

uniform bool debug_key_down < source = "key"; keycode = 0x46; mode = ""; >;
*/

/*=============================================================================
	Textures, Samplers, Globals, Structs
=============================================================================*/

//do NOT change anything here. "hurr durr I changed this and now it works"
//you ARE breaking things down the line, if the shader does not work without changes
//here, it's by design.

#define MAX_LIGHT_LUMINANCE                                     512.0
#define SPHERE_LIGHT_RADIUS_SCALE                               0.5

uniform bool OVERLAY_OPEN < source = "overlay_open"; >;
uniform uint  FRAMECOUNT  < source = "framecount"; >;
uniform bool SCREENSHOT < source = "screenshot"; >;

texture ColorInputTex : COLOR;
texture DepthInputTex : DEPTH;
sampler ColorInput 	{ Texture = ColorInputTex; };
sampler DepthInput  { Texture = DepthInputTex; };

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_depth.fxh"
#include ".\MartysMods\mmx_math.fxh"
#include ".\MartysMods\mmx_qmc.fxh"
#include ".\MartysMods\mmx_deferred.fxh"
#include ".\MartysMods\mmx_camera.fxh"
#include ".\MartysMods\mmx_bxdf.fxh"
#include ".\MartysMods\mmx_debug.fxh"

texture SobolSamplerTex         < source = "iMMERSE_sobolsampler.png"; > { Width = 256; Height = 512;   Format = RGBA8; };
sampler	sSobolSamplerTex        { Texture = SobolSamplerTex;   MinFilter=POINT; MipFilter=POINT; MagFilter=POINT; AddressU = WRAP; AddressV = WRAP; };

texture RELIGHT_ZBuffer         { Width = BUFFER_WIDTH/2; Height = BUFFER_HEIGHT/2; Format = R16F; MipLevels = 2; };
sampler sRELIGHT_ZBuffer	    { Texture = RELIGHT_ZBuffer; /* MinFilter = POINT; MipFilter = POINT; MagFilter = POINT; */ };

texture RELIGHT_Aux0            { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA16F; MipLevels = 5;};
sampler sRELIGHT_Aux0           { Texture = RELIGHT_Aux0; };

texture RELIGHT_Aux1            { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA16F; };
sampler sRELIGHT_Aux1           { Texture = RELIGHT_Aux1; };
sampler sRELIGHT_Aux1Point      { Texture = RELIGHT_Aux1;  MinFilter=POINT; MagFilter =POINT; MipFilter=POINT;};
texture RELIGHT_Aux2            { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA16F; };
sampler sRELIGHT_Aux2           { Texture = RELIGHT_Aux2; };

texture RELIGHT_SSSCullingMask  { Width = BUFFER_WIDTH>>3; Height = BUFFER_HEIGHT>>3; Format = R8; };
sampler sRELIGHT_SSSCullingMask { Texture = RELIGHT_SSSCullingMask; MinFilter=POINT; MagFilter =POINT; MipFilter=POINT;  };

texture RELIGHT_SSSRaw          { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA16F; };
sampler sRELIGHT_SSSRaw         { Texture = RELIGHT_SSSRaw; MinFilter= POINT; MagFilter = POINT; MipFilter= POINT; AddressU = CLAMP; AddressV = CLAMP; };

texture RELIGHT_GBufferPrev     { Width = BUFFER_WIDTH; Height = BUFFER_HEIGHT; Format = RGBA16F; };
sampler sRELIGHT_GBufferPrev    { Texture = RELIGHT_GBufferPrev; };

texture RELIGHT_RadianceTex     { Width = BUFFER_WIDTH/3;   Height = BUFFER_HEIGHT/3; Format = RGBA16F; };
sampler sRELIGHT_RadianceTex    { Texture = RELIGHT_RadianceTex; };

texture RELIGHT_M1Tex           { Width = BUFFER_WIDTH/3; Height = BUFFER_HEIGHT/3; Format = RGBA16F;};
sampler sRELIGHT_M1Tex          { Texture = RELIGHT_M1Tex; };
texture RELIGHT_M2Tex           { Width = BUFFER_WIDTH/3; Height = BUFFER_HEIGHT/3; Format = RGBA16F;};
sampler sRELIGHT_M2Tex          { Texture = RELIGHT_M2Tex; };

#if _COMPUTE_SUPPORTED

texture RELIGHT_HiZMipChain     { Width = BUFFER_WIDTH + 128; Height = BUFFER_HEIGHT + 128; Format = RG32F; MipLevels = 8;};
sampler sRELIGHT_HiZMipChain	{ Texture = RELIGHT_HiZMipChain;              MinFilter = POINT; MipFilter = POINT; MagFilter = POINT; };
storage stRELIGHT_HiZMipChain0	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 0;};
storage stRELIGHT_HiZMipChain1	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 1;};
storage stRELIGHT_HiZMipChain2	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 2;};
storage stRELIGHT_HiZMipChain3	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 3;};
storage stRELIGHT_HiZMipChain4	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 4;};
storage stRELIGHT_HiZMipChain5	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 5;};
storage stRELIGHT_HiZMipChain6	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 6;};
storage stRELIGHT_HiZMipChain7	{ Texture = RELIGHT_HiZMipChain;  MipLevel = 7;};

struct CSIN 
{
    uint3 groupthreadid     : SV_GroupThreadID;         
    uint3 groupid           : SV_GroupID;            
    uint3 dispatchthreadid  : SV_DispatchThreadID;     
    uint threadid           : SV_GroupIndex;
};

#endif

struct VSOUT
{
    float4 vpos : SV_Position;
    float2 uv   : TEXCOORD0;
};

#define LIGHT_TYPE_SPHERE       0
#define LIGHT_TYPE_INFINITE     1

struct LightDesc
{
    float3 param0; 
    float penumbra;   
    float3 radiance;   
    int type;
};

struct TraceContext
{
    float2 uv;
    uint2 texel;
    float3 pos;
    float3 normal;
    float3 geonormal;
    float3 viewdir;
    float depth;
    float4 jitter;
};

/*=============================================================================
	Common Functions
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

float3 srgb_to_acescg(float3 srgb)
{
    float3x3 m = float3x3(  0.613097, 0.339523, 0.047379,
                            0.070194, 0.916354, 0.013452,
                            0.020616, 0.109570, 0.869815);
    return mul(m, srgb);           
}

float3 acescg_to_srgb(float3 acescg)
{     
    float3x3 m = float3x3(  1.704859, -0.621715, -0.083299,
                            -0.130078,  1.140734, -0.010560,
                            -0.023964, -0.128975,  1.153013);                 
    return mul(m, acescg);            
}

float3 srgb_to_AgX(float3 srgb)
{
    float3x3 toagx = float3x3(0.842479, 0.0784336, 0.0792237, 
                              0.042328, 0.8784686, 0.0791661, 
                              0.042376, 0.0784336, 0.8791430);
    return mul(toagx, srgb);         
}

float3 AgX_to_srgb(float3 AgX)
{   
    float3x3 fromagx = float3x3(1.19688,  -0.0980209, -0.0990297,
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
    color  = saturate(color);
    color = cone_overlap(color);
    color = color*0.283799*((2.52405+color)*color);    
    //color = srgb_to_AgX(color);
    color = color * rcp(1.04 - saturate(color));    
    return color;
}

float3 pack_hdr(float3 color)
{
    color =  1.04 * color * rcp(color + 1.0);   
    //color = AgX_to_srgb(color);    
    color  = saturate(color);
    color = 1.14374*(-0.126893*color+sqrt(color));
    color = cone_overlap_inv(color);
    return color;   
}

//move  to  rstl
float3 spherical_to_cartesian(float2 azele)
{
    float2 scaz; sincos(azele.x, scaz.x, scaz.y);
    float2 sce;  sincos(azele.y,  sce.x,  sce.y);
    return float3(scaz.y * sce.y, sce.x, scaz.x * sce.y);
}

//replace with rstl
float2 anisotropy_map(float2 kernel, float3 n)
{    
    float anisotropy_limit = 0.8;
    n.xy *= anisotropy_limit;
    float2 distorted = kernel - n.xy * dot(n.xy, kernel);
    return distorted;
}

//replace with rstl
float2 anisotropy_map2(float2 kernel, float3 n)
{    
    float anisotropy_limit = 0.5;
    n.xy *= anisotropy_limit;
    float cosine = rsqrt(1 - dot(n.xy, n.xy));

    float2 distorted = kernel - n.xy * dot(n.xy, kernel) * cosine;
    return distorted * cosine;
}

float4 bilinear_split(float2 uv, float2 texsize)
{
    return float4(floor(uv * texsize - 0.5), frac(uv * texsize - 0.5));
}

float4 get_bilinear_weights(float4 bilinear)
{
    float4 w = float4(bilinear.zw, 1 - bilinear.zw);
    return w.zxzx * w.wwyy;
}

float2 deproject_dir(float3 origin, float3 dir)
{
    return Camera::proj_to_uv(origin + dir).xy - Camera::proj_to_uv(origin).xy;
}

uint unorm_float_to_uint(float f)
{
    return uint(f * 255.0 + 0.5);    
}

uint xor_uint8(uint a, uint b)
{
#if _COMPUTE_SUPPORTED
    return a ^ b;
#else
    uint flat_idx = a + b * 256u;
    return unorm_float_to_uint(tex2Dfetch(sSobolSamplerTex, uint2(flat_idx % 256u, (flat_idx / 256u) + 256u)).b);
#endif
}

float sobolsampler(uint2 p, uint dim)
{
    p %= 128u;
    uint sample_index = FRAMECOUNT % 128u;
    uint rank_idx =  dim      + (p.x + p.y * 128) * 8;
    uint owen_idx = (dim % 8) + (p.x + p.y * 128) * 8;

    uint rank = unorm_float_to_uint(tex2Dfetch(sSobolSamplerTex, uint2(rank_idx % 256, rank_idx / 256)).x); 
    uint owen = unorm_float_to_uint(tex2Dfetch(sSobolSamplerTex, uint2(owen_idx % 256,  owen_idx / 256)).y);
    uint sobol_i = dim + xor_uint8(sample_index, rank) * 256;
    uint sobol   = unorm_float_to_uint(tex2Dfetch(sSobolSamplerTex, uint2(sobol_i % 256, sobol_i / 256)).z);
    return frac((0.5 + xor_uint8(sobol, owen)) / 256.0);
}

/*=============================================================================
	Input Processing
=============================================================================*/

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    return o;
}

void ZWritePS(in VSOUT i, out float o : SV_Target0)
{
    float4 texels; //TODO: replace with gather()
    texels.x = Depth::get_linear_depth(i.uv + float2( 0.5, 0.5) * BUFFER_PIXEL_SIZE);
    texels.y = Depth::get_linear_depth(i.uv + float2(-0.5, 0.5) * BUFFER_PIXEL_SIZE);
    texels.z = Depth::get_linear_depth(i.uv + float2( 0.5,-0.5) * BUFFER_PIXEL_SIZE);
    texels.w = Depth::get_linear_depth(i.uv + float2(-0.5,-0.5) * BUFFER_PIXEL_SIZE);
    o = maxc(texels);
    o = Camera::depth_to_z(o);
}

void AlbedoWritePS(in VSOUT i, out float3 o : SV_Target0)
{     
    o = 0;   
    [unroll]for(int x = -1; x <= 1; x++)
    [unroll]for(int y = -1; y <= 1; y++)
    {
        float2 tuv = i.uv + BUFFER_PIXEL_SIZE * float2(x, y);       
        float3 albedo = tex2D(ColorInput, tuv).rgb;
        albedo = length(albedo) * normalize(unpack_hdr(albedo) + 0.025); //fix for 0 albedo and desaturate sliiiightly
        albedo /= max(1, maxc(albedo)); 
        float3 light_there = tex2D(sRELIGHT_Aux1, tuv).rgb;
        o += albedo * light_there;
    }        
    o /= 9.0;   
}

TraceContext _TraceContext(in uint2 working_pos, in uint2 working_size)
{
    TraceContext o;
    o.texel   = working_pos;
    o.uv      = pixel_idx_to_uv(o.texel, working_size);
    o.depth   = Depth::get_linear_depth(o.uv);
    o.pos     = Camera::uv_to_proj(o.uv, Camera::depth_to_z(o.depth));
    o.normal  = Deferred::get_normals(o.uv);
    o.geonormal = Deferred::get_geometry_normals(o.uv);
    o.viewdir = normalize(o.pos);
    o.pos     *= 0.999; //bias
    o.jitter.x = sobolsampler(o.texel, 0);
    o.jitter.y = sobolsampler(o.texel, 1);
    o.jitter.z = sobolsampler(o.texel, 2);
    o.jitter.w = sobolsampler(o.texel, 3);
    return o;
}

float2 blackbody_xy(float temperature) 
{
    float term = 1000.0 / temperature;

    const float4 xc_coefficients[2] = 
    {
        float4(-3.0258469, 2.1070379, 0.2226347, 0.240390), 
        float4(-0.2661293,-0.2343589, 0.8776956, 0.179910) 
    };

    const float4 yc_coefficients[3] =
    {
        float4(-1.1063814,-1.34811020, 2.18555832,-0.20219683), 
        float4(-0.9549476,-1.37418593, 2.09137015,-0.16748867), 
        float4( 3.0817580,-5.87338670, 3.75112997,-0.37001483)
    };

    float3 xyz;

    float4 xc;
    xc.w = 1.0;
    xc.xyz = term;
    xc.xy *= term;
    xc.x *= term;

    float x = dot(xc, temperature > 4000.0 ? xc_coefficients[0] : xc_coefficients[1]); //xc

    float4 yc;
    yc.w = 1.0;
    yc.xyz = x;
    yc.xy *= x;
    yc.x *= x;

    float y = dot(yc, temperature < 2222.0 ? yc_coefficients[0] : (temperature < 4000.0 ? yc_coefficients[1] : yc_coefficients[2])); //yc

    return float2(x, y);
}

float3 temp_tint_to_rgb(float2 tt)
{ 
    tt *= abs(tt);
    //center it so it _exactly_ is white at 0, 0
    //errors probably due to precision BS or whatever
    tt += float2(0.017588 + 0.0025, -0.037);
    
    float temp = tt.x < 0.0 ? lerp(1666.6, 5500.0, tt.x + 1.0) : lerp(5500.0, 16000.0, tt.x);
    float tint = tt.y * 0.125;
    
    float2 xy = blackbody_xy(temp);    
    float2 tangent = blackbody_xy(temp + 1.0) - xy;
    
    xy += normalize(float2(tangent.y, -tangent.x)) * tint;
    
    float3 XYZ;
    XYZ.y = 1.0; //some safe low value to remain in RGB gamut somewhat
    XYZ.x = (XYZ.y / xy.y) * xy.x;
    XYZ.z = (XYZ.y / xy.y) * (1.0 - xy.x - xy.y);
    
    const float3x3 XYZ_to_linear_sRGB = float3x3(2.36461385, -0.86954057, -0.46807328,
                                                -0.51516621,1.4264081, 0.0887581,
                                                 0.0052037,-0.01440816, 1.00920446);            
    float3 rgb = mul(XYZ_to_linear_sRGB, XYZ);
    rgb /= maxc(rgb);
    rgb = saturate(rgb)+0.01; //for some reason it can't be 0? I am so confused
    return rgb;   
}

LightDesc _LightDesc(float2 tt, float intensity, float penumbra, bool enabled, int type, float2 azele, float3 pos)
{
    LightDesc L;

    float3 tone = temp_tint_to_rgb(tt);
    tone = length(unpack_hdr(1.0)) * normalize(unpack_hdr(tone));

    L.type     = type;
    L.radiance = tone * intensity * intensity * enabled;
    L.penumbra = penumbra;

    [branch]
    if(L.type == LIGHT_TYPE_INFINITE)
    {
        L.param0 = spherical_to_cartesian(azele * float2(TAU, PI) + float2(0, -HALF_PI)).xzy;
    }
    else
    {
        L.param0 = Camera::uv_to_proj(float2(pos.x, 1 - pos.y), Camera::depth_to_z(pos.z * pos.z * pos.z));
    }

    return L;
}


void init_lights(out LightDesc lights[AMOUNT_OF_LIGHTS])
{
    lights[0] = _LightDesc(LIGHT0_TT, LIGHT0_INT, LIGHT0_PENUM, LIGHT0_ENABLE, LIGHT0_TYPE, LIGHT0_AZELE, LIGHT0_POS);
#if AMOUNT_OF_LIGHTS > 1
    lights[1] = _LightDesc(LIGHT1_TT, LIGHT1_INT, LIGHT1_PENUM, LIGHT1_ENABLE, LIGHT1_TYPE, LIGHT1_AZELE, LIGHT1_POS);
#endif
#if AMOUNT_OF_LIGHTS > 2
    lights[2] = _LightDesc(LIGHT2_TT, LIGHT2_INT, LIGHT2_PENUM, LIGHT2_ENABLE, LIGHT2_TYPE, LIGHT2_AZELE, LIGHT2_POS);
#endif
#if AMOUNT_OF_LIGHTS > 3
    lights[3] = _LightDesc(LIGHT3_TT, LIGHT3_INT, LIGHT3_PENUM, LIGHT3_ENABLE, LIGHT3_TYPE, LIGHT3_AZELE, LIGHT3_POS);
#endif    
}

/*=============================================================================
	Tracing - Regular
=============================================================================*/

struct HybridRayDesc
{
    float3 origin;
    float t3d;
    float3 dir;    
    float t2d;
    float2 target_uv;    
    float throughput;
};

float disc_cdf(float x)
{
    return x * sqrt(saturate(1 - x * x)) + (HALF_PI - Math::fast_acos(x));//asin(x);
}

float2 sample_cut_disc(float A, float rand)
{   
    float signedA = A;
    A = min(abs(A), HALF_PI);
    //todo replace with Heitz's triangle cut
    float polyfit = mad(mad(mad(mad(mad(-0.0079908617, A, 0.0238255409), A, -0.0283903598), A, 0.0198450184), A, -0.0574433620), A, 0.7400712465);
    
    float2 d;
    d.x = Math::fast_sign(signedA) * (1 - polyfit * pow(HALF_PI - A, 0.66666666));
    d.y = (2 * rand - 1) * sqrt(saturate(1 - d.x * d.x));
    return d;
}

//mostly https://momentsingraphics.de/I3D2019.html
//with a few modifications to accomodate for uncoupled light intensity vs radius and to handle points inside the lights
float4 sample_projected_spherical_cap(float3 light_center, float light_radius, float3 p, float3 n, float2 rand01)
{
    //compute geometry
    float3 d = light_center - p;
    float dd2 = dot(d, d);

    float3 omegad = d * rsqrt(dd2);

    //build orthonormal basis around n such that the vector to the light lies in XZ plane
    float3 z = n;
    float3 x = omegad - dot(z, omegad) * z; 
    float u = rsqrt(dot(x, x));
    x *= u;
    float3 y = cross(z, x);

    float3 R, C; 
    R.y = light_radius * rsqrt(dd2);

    //PG: R.y > 1 inside the sphere, so do a soft clamp
    R.y = sqrt(R.y * R.y / (1.0 + R.y * R.y));

    R.x = dot(z, omegad) * R.y;
    R.z = dot(x, omegad) * R.y;

    float v = sqrt(saturate(1 - R.y * R.y));

    C.x = dot(x, omegad) * v;
    C.z = dot(z, omegad) * v;
    C.y = 0;

    float2 T;
    T.x = u * v;
    T.y = sqrt(saturate(1 - T.x * T.x));
 
    float3 omegaI = omegad;
    float ipdf = 0;

    float AD = HALF_PI - disc_cdf(T.x);

    [branch]
    if(R.x >= 0 && T.x >= 1)//entirely above
    {       
        float AE = R.x * R.y * PI;//area
        float2 D = sample_cut_disc(PI * rand01.x - HALF_PI, rand01.y);

        omegaI.x = R.x * D.x + C.x;
        omegaI.y = R.y * D.y;
        omegaI.z = sqrt(saturate(1 - dot(omegaI.xy, omegaI.xy)));

        ipdf = AE;
    }
    else if(R.x >= 0)//mostly above
    {
        float AEs = HALF_PI + disc_cdf((T.x - C.x) / R.x);
        float AE = R.x * R.y * AEs;

        ipdf = AE + AD;

        if(rand01.x < AE / (AE + AD))
        {
            float2 D = sample_cut_disc(rand01.x * (AE + AD) / (R.x * R.y) - HALF_PI, rand01.y);

            omegaI.x = R.x * D.x + C.x;
            omegaI.y = R.y * D.y;           
        }
        else 
        {
            float2 D = sample_cut_disc((AE + AD) * (1 - rand01.x) - HALF_PI, rand01.y);

            omegaI.x = -D.x;
            omegaI.y = D.y;           
        }
        omegaI.z = sqrt(saturate(1 - dot(omegaI.xy, omegaI.xy)));
    }
    else if(T.x < 1) //mostly below
    {
        float3 D;
        D.xy = sample_cut_disc(AD * (1 - rand01.x) - HALF_PI, rand01.y);
        D.z = sqrt(1 - dot(D.xy, D.xy));

        omegaI.z = (C.z + R.z) / T.y * D.z;

        float sy = R.y * sqrt((R.z * R.z - (omegaI.z - C.z)*(omegaI.z - C.z)) / (R.z * R.z * (T.y * T.y - D.z * D.z)));
        omegaI.y = sy * D.y;
        omegaI.x = sqrt(saturate(1 - dot(omegaI.yz, omegaI.yz)));

        ipdf = ((C.z + R.z) * (C.z + R.z) * AD) / saturate(1.0 - T.x * T.x);
    }

    float3 out_dir = normalize(omegaI.x * x + omegaI.y * y + omegaI.z * z);   

    ipdf /= light_radius * light_radius * PI;
    ipdf *= dd2; //allow the original light falloff to take over 
    ipdf = max(ipdf, 0);   
    return float4(out_dir, ipdf);
}

float3 compile_dir_towards_center(float3 origin, LightDesc light)
{
    float3 dir = 0;
    [flatten]
    if(light.type == LIGHT_TYPE_SPHERE)
        dir = normalize(light.param0 - origin);
    else 
        dir = light.param0;

    return dir;
}

HybridRayDesc compile_ray(TraceContext ctx, LightDesc light)
{
    HybridRayDesc ray;
    ray.origin = ctx.pos;

    [flatten]
    if(light.type == LIGHT_TYPE_SPHERE)
        ray.dir = normalize(light.param0 - ray.origin);
    else 
        ray.dir = light.param0;

    ray.throughput = saturate(dot(ray.dir, ctx.normal));

    [branch]
    if(light.penumbra > 0.001) //safe epsilon for the complicated method
    {
        //for the infinite light, pretend it's a spherical light at a given distance and size and reuse spherical cap sampling for that
        float3 light_pos = light.type == LIGHT_TYPE_SPHERE ? light.param0 
                                                          : ctx.pos + ray.dir;
        float light_radius = light.type == LIGHT_TYPE_SPHERE ? SPHERE_LIGHT_RADIUS_SCALE * light.penumbra
                                                            : light.penumbra / (1 + light.penumbra); 

        float4 S = sample_projected_spherical_cap(light_pos, light_radius, ctx.pos, ctx.normal, ctx.jitter.zw);

        ray.dir         = S.xyz;
        ray.throughput  = S.w; 

        if(light.type == LIGHT_TYPE_SPHERE)
            light.param0 = ctx.pos + ray.dir * length(light.param0 - ctx.pos);        
    }

    [branch]
    if(light.type == LIGHT_TYPE_SPHERE)
    {
        ray.target_uv = Camera::proj_to_uv(light.param0);
    }        
    else
    {
        float2 uv_dir = Camera::proj_to_uv(ray.origin + ray.dir).xy - ctx.uv;
        ray.target_uv = Math::aabb_hit_01(ctx.uv, uv_dir);
    }

    return ray;
}

float spline(float l)
{
    float sharpness = 4.0;
    return (exp2(sharpness * l) - 1) / (exp2(sharpness) - 1);     
}

float hyperbolize_depth(float z)
{
    float f = RESHADE_DEPTH_LINEARIZATION_FAR_PLANE;
    return z * f * rcp(1 + z * (f - 1));
}

float linearize_depth(float x)
{
    x /= RESHADE_DEPTH_LINEARIZATION_FAR_PLANE - x * (RESHADE_DEPTH_LINEARIZATION_FAR_PLANE - 1.0); 
    return x;
}

float3 proj_to_clip(float3 p)
{
    p.xy = Camera::proj_to_uv(p);
    p.z = hyperbolize_depth(Camera::z_to_depth(p.z));
    return p;
}

float get_ray_time_from_uv(float2 uv, HybridRayDesc ray)
{
    float3 pos = Camera::uv_to_proj(uv, 1);
    float A = dot(ray.origin, ray.dir);    
    float B = dot(pos, ray.dir);
    float C = dot(pos, ray.origin);
    float D = dot(pos, pos); 
    return (B * C - D * A) * rcp(D - B * B);
}

#if _COMPUTE_SUPPORTED

bool find_intersection_hiz(TraceContext ctx, inout HybridRayDesc ray, float quality)
{  
    ray.t3d = get_ray_time_from_uv(ray.target_uv, ray);  

    float3 origin_vs = ctx.pos + ctx.normal * 0.05;   
    float3 end_vs = origin_vs + ray.t3d * ray.dir;

    [flatten] //swap end and origin as hiz has issues with rays going backwards. These can be fixed but at the cost of a lot of performance
    if(end_vs.z < origin_vs.z)
    {
        float3 tmp = end_vs;
        end_vs = origin_vs;
        origin_vs = tmp;
    }  
 
    float3 origin_ss = float3(Camera::proj_to_uv(origin_vs), hyperbolize_depth(Camera::z_to_depth(origin_vs.z)));
    float3 end_ss = float3(Camera::proj_to_uv(end_vs), hyperbolize_depth(Camera::z_to_depth(end_vs.z)));

    float3 delta_ss = end_ss - origin_ss; 
    float3 step = Math::fast_sign(delta_ss);
    float2 step_offset = BUFFER_PIXEL_SIZE * step.xy * 0.999; //nudge a bit inside to fix some outlines
    step = saturate(step);
    float3 delta_ss_inv = rcp(delta_ss);
    delta_ss_inv = abs(delta_ss_inv) < 0.000001.xxx ? 0.0.xxx : delta_ss_inv;
    
    float curr_t = 0; 
    int curr_mip = 0;

    int j = 0;
    bool hit = false;  

    [loop]
    while(curr_mip >= 0 && j++ < 1024)
    {
        float2 curr_uv        = origin_ss.xy + delta_ss.xy * curr_t;  
        float2 curr_layer_res = BUFFER_SCREEN_SIZE * exp2(-curr_mip); 
        float2 curr_texel     = floor(curr_uv * curr_layer_res);

        float2 minmax_z = abs(tex2Dfetch(sRELIGHT_HiZMipChain, int2(curr_texel), curr_mip).xy) * 1.001; //bias, abs cuz negated in construction         

        float2 t = ((curr_texel + step.xy) / curr_layer_res + step_offset - origin_ss.xy) * delta_ss_inv.xy;
        float mint_xy = min(t.x, t.y);

        float thickness = SHADOWS_OBJ_THICKNESS * SHADOWS_OBJ_THICKNESS * (1 + minmax_z.x * 0.01);

        minmax_z.y = Camera::z_to_depth(minmax_z.y + thickness);        
        minmax_z.y = hyperbolize_depth(minmax_z.y);
        minmax_z.x = Camera::z_to_depth(minmax_z.x);
        minmax_z.x = hyperbolize_depth(minmax_z.x);   

        float2 minmaxt_z = (minmax_z - origin_ss.z) * delta_ss_inv.z;         
        curr_mip--;
        
        [flatten]
        if(minmaxt_z.x < mint_xy && curr_t <= minmaxt_z.y)
        {
            curr_t = max(curr_t, minmaxt_z.x);
        }
        else
        {
            curr_t = mint_xy;
            curr_mip = min(curr_mip + 2, 7);           
        }   

        float3 hitp = origin_ss + delta_ss * curr_t;
        hitp.z = Camera::depth_to_z(linearize_depth(hitp.z));
        hitp = Camera::uv_to_proj(hitp.xy, hitp.z);

        float hit_dist = distance(hitp, origin_vs);

        [branch]
        if(hit_dist >= ray.t3d)
        {
            hit = true;            
            ray.t3d = hit_dist; //save for later

            j = 10000;
        }
    }

    float3 hitp = origin_ss + delta_ss * curr_t;
    hitp.z = Camera::depth_to_z(linearize_depth(hitp.z));
    hitp = Camera::uv_to_proj(hitp.xy, hitp.z);

    float hit_dist = distance(hitp, origin_vs);
    ray.t3d = hit_dist;
    return !hit;
}

#endif

bool intersects(float ray_z, float actual_z)
{
    float thickness = (1 + actual_z * 0.01) * SHADOWS_OBJ_THICKNESS * SHADOWS_OBJ_THICKNESS;    
    float delta = actual_z - ray_z;
    return abs(delta * 2.0 + thickness + 0.05) < thickness;
}

bool find_intersection_hybrid_dda(TraceContext ctx, inout HybridRayDesc ray, float quality, int mip)
{    
    float uv_dist = length((ray.target_uv - ctx.uv) * BUFFER_ASPECT_RATIO.yx);  
    int steps = ceil(quality * uv_dist + 1.0);
    steps = clamp(steps, 1, 254);
    float divisor = rcp(quality * uv_dist + 1.0);

    float A = dot(ray.origin, ray.dir);
    int u = 0;

    [loop]
    for(u = 0; u <= steps; u += 4)
    {  
        float4 z;
        
        //batching accesses for latency hiding
        [unroll]for(int k = 0; k < 4; k++)
        {
            ray.t2d = saturate((u + k + ctx.jitter.x) * divisor);
            float2 uv = lerp(ctx.uv, ray.target_uv, spline(ray.t2d));
            z[k] = tex2Dlod(sRELIGHT_ZBuffer, uv, mip).x;
        }

        float4 hit_t3d;
        
        [unroll]for(int k = 0; k < 4; k++)
        {
            ray.t2d = saturate((u + k + ctx.jitter.x) * divisor);
            float2 uv = lerp(ctx.uv, ray.target_uv, spline(ray.t2d));
            float3 pos = Camera::uv_to_proj(uv, 1.0);

            float B = dot(pos, ray.dir);
            float C = dot(pos, ray.origin);
            float D = dot(pos, pos);   

            hit_t3d[k] = (B * C - D * A) * rcp(D - B * B);
            hit_t3d[k] = abs(hit_t3d[k]);
        }

        [loop]
        for(int k = 0; k < 4; k++)
        {
            ray.t3d = hit_t3d[k];
            float ray_z = ray.origin.z + ray.dir.z * ray.t3d;           

            [flatten]
            if(intersects(ray_z, z[k]))
            {
                u = 80085;               
                break;
            }
        }                                 
    }

    return u > steps * 2;  
}

bool find_intersection(TraceContext ctx, inout HybridRayDesc ray, float quality)
{
#if _COMPUTE_SUPPORTED
    [branch]
    if(SHADOW_Q == 4) 
        return find_intersection_hiz(ctx, ray, quality);
    else 
        return find_intersection_hybrid_dda(ctx, ray, quality, 0);
#else 
    return find_intersection_hybrid_dda(ctx, ray, quality);
#endif
}

float point_light_atten(float r, float ldotl)
{
    float r2 = r * r;
    return 2 * rcp(ldotl + r2 + sqrt(ldotl * ldotl + ldotl * r2)); //a little bit less numerically stable but faster
    //return 2 * rcp(ldotl + r2 + sqrt(ldotl) * sqrt(ldotl + r2)); //more numerically stable
    //return 2 * rcp(r2) * saturate(1 - sqrt(ldotl) * rsqrt(ldotl + r2));
}

float3 evaluate_radiance(LightDesc light, float3 pos)
{
    float3 intensity = MAX_LIGHT_LUMINANCE * light.radiance;

    [flatten]
    if(light.type == LIGHT_TYPE_SPHERE)
    {
        float3 L = light.param0 - pos;
        intensity *= point_light_atten(SPHERE_LIGHT_RADIUS_SCALE, dot(L, L));
    } 
    else
    {
        intensity *= 0.02; //compensate for the fact that the infinite light has no distance attenuation
    }

    return intensity;
}

float spline2(float l)
{
    float sharpness = 4.0;
    return (exp2(sharpness * l) - 1) / (exp2(sharpness) - 1);     
}

void TraceLightsPS(in VSOUT i, out float4 o : SV_Target0)
{
    LightDesc lights[AMOUNT_OF_LIGHTS];  
    init_lights(lights);

    TraceContext ctx = _TraceContext(i.vpos.xy, BUFFER_SCREEN_SIZE);

    const float quality_preset[5] = {32,48,64,192,192};
    float quality_mult = quality_preset[SHADOW_Q]; 

    float3 accumulated = 0;

    [unroll]
    for(int j = 0; j < AMOUNT_OF_LIGHTS; j++)
    {
        float3 intensity = evaluate_radiance(lights[j], ctx.pos);
        HybridRayDesc ray = compile_ray(ctx, lights[j]);
        intensity *= ray.throughput; 
        intensity *= step(0, dot(ray.dir, ctx.geonormal)); //clip normals that would trace into geometry anyways

        if(SHADOW_MODE >= 1)
        {
            [branch]
            if(dot(intensity, 1) > 0.0)
            {
                intensity *= !find_intersection(ctx, ray, quality_mult); 
            }
        }

        accumulated += intensity;
    }

    [branch]
    if(SHADOW_MODE == 2)
    {     
        float4 nextbounce = 0;
        float step_limit = SHADOW_Q >= 3 ? 24 : 12;

        float T = SHADOWS_OBJ_THICKNESS * SHADOWS_OBJ_THICKNESS * (1 + ctx.pos.z * 0.01);
        float3 v = -ctx.viewdir;

        float3 slice_dir = 0; sincos(ctx.jitter.x * PI, slice_dir.x, slice_dir.y);               
        float3 ortho_dir = slice_dir - dot(slice_dir.xy, v.xy) * v;
        
        float3 slice_n = cross(slice_dir, v); 
        slice_n *= rsqrt(dot(slice_n, slice_n)); 

        float3 n_proj_on_slice = ctx.normal - slice_n * dot(ctx.normal, slice_n);
        float sliceweight = sqrt(dot(n_proj_on_slice, n_proj_on_slice));
        
        float cosn = saturate(dot(n_proj_on_slice, v) * rcp(sliceweight));
        float normal_angle = Math::fast_acos(cosn) * Math::fast_sign(dot(ortho_dir, n_proj_on_slice));
        
        float2 scaled_dir = slice_dir.xy * BUFFER_ASPECT_RATIO;
        uint occlusion_bitfield = 0xFFFFFFFF;

        [unroll]
        for(int side = 0; side < 2; side++)
        {        
            float2 limit_uv = Math::aabb_hit_01(ctx.uv, scaled_dir);    
            float limit_len = length((limit_uv - ctx.uv) * BUFFER_ASPECT_RATIO.yx);
            int steps = ceil(limit_len * step_limit);

            [loop]         
            for(int _sample = 0; _sample < steps; _sample++)
            {
                float s = spline2((_sample + ctx.jitter.y) / steps);             
                float2 tap_uv = lerp(ctx.uv, limit_uv, s);

                int mip = min(3, int(log2(s * limit_len * BUFFER_WIDTH) - 5.0));
                float zz = tex2Dlod(sRELIGHT_ZBuffer, tap_uv.xy, mip).x;

                float3 pp = Camera::uv_to_proj(tap_uv, zz);
                float3 dv = pp - ctx.pos;                

                float ddotv = dot(dv, v);
                float ddotd = dot(dv, dv);
                float2 h = float2(ddotv, ddotv - T) * rsqrt(float2(ddotd, ddotd - T * (2 * ddotv - T)));
                h = Math::fast_acos(h);                        ;
                h = saturate(((side ? h : -h.yx) + normal_angle) / PI + 0.5);
                h = h * h * (3.0 - 2.0 * h);

                uint a = uint(h.x * 32);
                uint b = ceil(saturate(h.y - h.x) * 32);
                uint occlusion = ((1 << b) - 1) << a;                
                
                uint local_bitfield = occlusion_bitfield & ~occlusion;
                uint changed_bits = local_bitfield ^ occlusion_bitfield;
                occlusion_bitfield = local_bitfield;                 

                if(!changed_bits) continue;
                float3 hn = Deferred::get_normals(tap_uv);
                float ndotl = dot(hn, -dv);
                if(ndotl < 0) continue;
                
                float3 bounce = tex2Dlod(sRELIGHT_RadianceTex, tap_uv, 0).rgb;
                float visibility = saturate(countbits(changed_bits) / 32.0) * sliceweight;
                visibility *= saturate(dot(dv, n_proj_on_slice) / sliceweight * rsqrt(ddotd));
                nextbounce.rgb += bounce * visibility;                             
            }        
            scaled_dir = -scaled_dir;
        }
        nextbounce.w += sliceweight;
        
        nextbounce.rgb /= nextbounce.w;
        nextbounce *= 2;
        accumulated += nextbounce.rgb;            
    }

    o.rgb = accumulated + AMBIENT_INT * AMBIENT_INT * (!USE_ALBEDO_ESTIMATION);
    o.w = ctx.pos.z;   
}

/*=============================================================================
	Subsurface Scattering
=============================================================================*/

float3 rgb_to_hcv(in float3 RGB)
{
    RGB = saturate(RGB);
    float Epsilon = 1e-10;        
    float4 P = (RGB.g < RGB.b) ? float4(RGB.bg, -1.0, 2.0/3.0) : float4(RGB.gb, 0.0, -1.0/3.0);
    float4 Q = (RGB.r < P.x) ? float4(P.xyw, RGB.r) : float4(RGB.r, P.yzx);
    float C = Q.x - min(Q.w, Q.y);
    float H = abs((Q.w - Q.y) / (6 * C + Epsilon) + Q.z);
    return float3(H, C, Q.x);
}

float3 rgb_to_hsl(in float3 RGB)
{
    float3 HCV = rgb_to_hcv(RGB);
    float L = HCV.z - HCV.y * 0.5;
    float S = HCV.y / (1.0000001 - abs(L * 2 - 1));
    return float3(HCV.x, S, L);
}

float skindetect(float3 c, float z)
{
    float3 hsl = rgb_to_hsl(c);  
    float mask_hue = SSS_HUE_MASK_CENTER / 360.0;
    float mask_hue_range = SSS_HUE_MASK_RANGE;
    float dist_to_hue = min(abs(hsl.x - mask_hue), abs(hsl.x - mask_hue + 1));
    dist_to_hue = min(dist_to_hue, abs(hsl.x - mask_hue - 1.0));
    float w = smoothstep(mask_hue_range, 0, dist_to_hue);
    w *= smoothstep(0, 0.05, hsl.z) * smoothstep(1, 0.95, hsl.z) * smoothstep(0, 0.2, hsl.y);     
    return saturate(w * exp2(-z*z*1e4)); 
}

//float based, reasonably unbiased to generate new seeds
//random walk suffers from curse of dimensionality so it's not a problem
//to use white noise here
float4 permute_hash(float4 p4)
{
	p4 = frac(p4 * float4(0.1031, 0.1030, 0.0973, 0.1099));
    p4 += dot(p4, p4.wzxy + 33.33);
    return frac((p4.xxyz + p4.yzzw) * p4.zywx);
}

bool is_skin_tile(uint2 fullscreen_texel)
{
    return tex2Dfetch(sRELIGHT_SSSCullingMask, fullscreen_texel / 8).x > 0.5;
}

VSOUT SubsurfaceScatteringVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 

    if(!USE_SSS)
    {
        o.vpos = 0;
    }

    return o;
}

void SubsurfaceCullingMaskPS(in VSOUT i, out float4 o : SV_Target0)
{    
    bool is_skin = false;

    [loop]
    for(int j = 0; j < 16; j++)
    {
        int2 texel = int2(i.vpos.xy) * 8 + int2(j / 4, j % 4) * 2;
        float2 uv = (texel + 0.5) * BUFFER_PIXEL_SIZE;
        float3 color = tex2Dlod(ColorInput, uv, 0).rgb;
        float z      = tex2Dlod(sRELIGHT_ZBuffer, uv, 1).x;
        float skinmask = skindetect(color, z / RESHADE_DEPTH_LINEARIZATION_FAR_PLANE);

        is_skin = skinmask > 1e-3 ? true : is_skin;
        if(is_skin) break;
    }

    o = is_skin;
}


struct Path 
{
    float3 last_vertex;
    float t;
    float3 direction;
    int depth;
    float3 throughput;
};

void SubsurfacePathtracePS(in VSOUT i, out float4 o : SV_Target0)
{
    if(!is_skin_tile(i.vpos.xy)) 
        discard; 

    const float hg_g = 0.9; //skin has 0.9

    TraceContext ctx = _TraceContext(i.vpos.xy, BUFFER_SCREEN_SIZE);

    Path path;
    path.last_vertex = Camera::uv_to_proj(i.uv) - ctx.normal * 0.02;
    path.depth       = 0;  
    path.throughput  = 1; 
    path.direction   = BXDF::sample_phase_henyey_greenstein(ctx.jitter.xy, hg_g);
    path.direction = mul(path.direction, Math::base_from_vector(ctx.viewdir));
    path.direction.xy *= Math::fast_sign(dot(path.direction, -ctx.geonormal));

    float scale = rcp(abs(SSS_RAD) + 1e-5) * 4.0;
    scale *= scale;

    //https://github.com/mmp/pbrt-v4/blob/39e01e61f8de07b99859df04b271a02a53d9aeb2/src/pbrt/media.cpp#L95
    float3 sigma_s = float3(0.74, 0.88, 1.01) * scale;
    float3 sigma_a = float3(0.032, 0.17, 0.48) * scale;
    float3 sigma_t = sigma_a + sigma_s;

    const int4 scattering_orders = int4(16,32,64,128);
    int max_depth = scattering_orders[SSS_Q]; 
    bool exited = false;

    [loop]
    while(path.depth++ < max_depth)
    {
        ctx.jitter = permute_hash(ctx.jitter);
        float4 u = ctx.jitter;

        //wavelength MIS
        float3 pmf_wavelength = path.throughput * (sigma_s / sigma_t); //albedo
        pmf_wavelength /= dot(pmf_wavelength, 1); //normalize

        float sigma_t_to_use = sigma_t.x;
        sigma_t_to_use = u.x > pmf_wavelength.x ? sigma_t.y : sigma_t_to_use;
        sigma_t_to_use = u.x > pmf_wavelength.y ? sigma_t.z : sigma_t_to_use;     
        path.t = -log(1 - u.y) / sigma_t_to_use;   

        //test 2 samples along the path
        float2 test_t = float2(0.5, 1) * path.t;
        float3 p0 = path.last_vertex + path.direction * path.t * 0.5;
        float3 p1 = path.last_vertex + path.direction * path.t;
        float2 z; 
        z.x = tex2Dlod(sRELIGHT_ZBuffer, Camera::proj_to_uv(p0), 0).x;
        z.y = tex2Dlod(sRELIGHT_ZBuffer, Camera::proj_to_uv(p1), 0).x;

        float2 delta = float2(p0.z, p1.z) - z;
        
        //path exited on other side, refine exit location and terminate
        [branch]if(any(delta < 0))
        {            
            float3 t_bounds; t_bounds.xy = delta.x < 0 ? float2(0, 0.5 * path.t) : float2(0.5 * path.t, path.t);   
            
            [unroll]for(int j = 0; j < 3; j++)
            {
                t_bounds.z = (t_bounds.x + t_bounds.y) * 0.5;
                float3 p_mid = path.last_vertex + path.direction * t_bounds.z;
                float z = tex2Dlod(sRELIGHT_ZBuffer, Camera::proj_to_uv(p_mid), 0).x;
                t_bounds.xy = p_mid.z < z ? t_bounds.xz : t_bounds.zy;
            }

            float free_flight = t_bounds.x;
            float3 tr = exp(-free_flight * sigma_t);
            float3 p_surface = tr;
            float3 pdf = pmf_wavelength * p_surface;

            path.throughput *= tr / dot(pdf, 1);
            path.last_vertex += path.direction * free_flight;   
            exited = true; 

            break;
        }

        //in-scattering
        float3 new_dir = BXDF::sample_phase_henyey_greenstein(u.zw, hg_g);
        new_dir = mul(new_dir, Math::base_from_vector(path.direction));
        float3 tr = exp(-path.t * sigma_t);
        float3 pdf_distance = sigma_t * tr;
        float3 pdf = pmf_wavelength * pdf_distance;
        path.throughput *= (tr * sigma_s) / dot(pdf, 1);

        path.last_vertex += path.direction * path.t;  
        path.direction = new_dir;


        if(dot(path.throughput, 0.333) < 0.01) break;
    }

    o = 0;
    o.w = tex2D(sRELIGHT_Aux0, i.uv).w;

    [branch]
    if(exited)
    {
        float2 exit_uv = Camera::proj_to_uv(path.last_vertex);
        float3 transmitted = tex2Dlod(sRELIGHT_Aux0, exit_uv, 0).rgb;
        float3 exit_normal = Deferred::get_normals(exit_uv);

        transmitted *= saturate(dot(path.direction, exit_normal) + 1); //a bit of masking to avoid leaking
        transmitted *= path.throughput;
        
        o.rgb += transmitted;
    }
}

void SubsurfaceDenoisePS(in VSOUT i, out float3 o : SV_Target0)
{
    if(!is_skin_tile(i.vpos.xy)) 
        discard; 
    
    float4 g = float4(Deferred::get_normals(i.uv), Camera::depth_to_z(Depth::get_linear_depth(i.uv)));
    float4 filtered_sss = 0;
   
    float3 p = Camera::uv_to_proj(i.uv, g.w);

    float2 u;
    u.x =  sobolsampler(i.vpos.xy, 0);
    u.y =  sobolsampler(i.vpos.xy, 1);

    filtered_sss += float4(tex2Dlod(sRELIGHT_SSSRaw, i.uv, 0).rgb, 1);

    [loop]for(int x = 0; x < 4; x++)
    [loop]for(int y = 0; y < 4; y++)
    {
        float2 fi = (float2(x, y) + u) / 4.0;
        fi = fi * 2.0 - 1.0;
        fi = sign(fi) * sqrt(-2 * log(1 - abs(fi)));

        float2 uv = i.uv + fi * BUFFER_PIXEL_SIZE * 7.5;
        float4 sss = tex2Dlod(sRELIGHT_SSSRaw, uv, 0);
        float3 n = Deferred::get_normals(uv);

        float3 tp = Camera::uv_to_proj(uv, sss.w);
        float pd = abs(dot(p - tp, n));
        pd += length(p - tp);

        float w_z = exp(-pd * pd * 256.0);  

        float w_n = dot(g.xyz, n.xyz);
        w_n = saturate(w_n*8-7);

        float w = w_z * w_n;
        filtered_sss.rgb += sss.rgb * w;
        filtered_sss.w += w;
    }

    o = filtered_sss.rgb / (filtered_sss.w + 1e-6);   
    float3 color = tex2Dlod(ColorInput, i.uv, 0).rgb;
    float skinmask = skindetect(color, g.w / RESHADE_DEPTH_LINEARIZATION_FAR_PLANE);
    o *= skinmask;

}

/*=============================================================================
	Filtering
=============================================================================*/

void SecondMomentPS(in VSOUT i, out PSOUT2 o)
{
    o.t0 = o.t1 = 0;
    [unroll]for(int x = -1; x <= 1; x++)
    [unroll]for(int y = -1; y <= 1; y++)
    {
        float3 v = tex2Dfetch(sRELIGHT_Aux0, int2(i.vpos.xy) * 3 + 1 + int2(x, y)).rgb;
        o.t0.rgb += v;
        o.t1.rgb += v * v;
    }

    o.t0.rgb /= 9;
    o.t1.rgb /= 9;
    o.t0.w = o.t1.w = 1;
}

void TemporalFilterPS(in VSOUT i, out float4 o : SV_Target0)
{
    if(SHADOW_MODE == 0)
    {
        o = tex2Dlod(sRELIGHT_Aux0, i.uv, 0);
        return;
    }

    float2 mv = Deferred::get_motion(i.uv);
    float2 prev_uv = i.uv + mv;

    float3 prev = tex2D(sRELIGHT_Aux1, prev_uv).rgb;
 
    bool valid_history = Math::inside_screen(prev_uv);
    float4 curr_gbuffer = float4(Deferred::get_normals(i.uv), Camera::depth_to_z(Depth::get_linear_depth(i.uv)));

    float blendfact = 1;

    if(valid_history)
    {
        float4 kernel = bilinear_split(prev_uv, BUFFER_SCREEN_SIZE);
        float4 weights = get_bilinear_weights(kernel);

        float sum_w = 0;

        prev = 0;

        for(int x = 0; x < 2; x++)
        for(int y = 0; y < 2; y++)
        {
            int2 offset = int2(x, y);
            int2 coord = int2(kernel.xy) + offset;

            float4 tap_sample = tex2Dfetch(sRELIGHT_Aux1, coord);
            float4 tap_gbuffer = tex2Dfetch(sRELIGHT_GBufferPrev, coord);

            float w_z = abs(tap_gbuffer.w - curr_gbuffer.w) / max3(tap_gbuffer.w, curr_gbuffer.w, 1e-6);
            w_z       = exp2(-w_z * 256.0);

            float w_n = dot(curr_gbuffer.xyz, tap_gbuffer.xyz);
            w_n       = Math::fast_acos(saturate(w_n));
            w_n       = smoothstep(25.0, 15.0, degrees(w_n));

            float w = w_z * w_n * weights[x + y * 2];

            prev += tap_sample.rgb * w;
            sum_w += w;
        }

        prev /= max(1e-6, sum_w);
        blendfact = sum_w;
    }

    if(blendfact < 1e-3) 
        valid_history = false;

    float3 curr = tex2Dlod(sRELIGHT_Aux0, i.uv, 0).rgb;    
       
    if(!valid_history)
    {
        o = float4(curr, curr_gbuffer.w);
        return;
    }

    float3 m1_curr, m2_curr, m1_prev, m2_prev;
    m1_curr = m2_curr = m1_prev = m2_prev = 0;

    [unroll]for(int x = -1; x <= 1; x++)
    [unroll]for(int y = -1; y <= 1; y++)   
    {
        float3 tprev = tex2Dlod(sRELIGHT_Aux1Point, prev_uv + float2(x, y) * BUFFER_PIXEL_SIZE, 0).rgb;
        m1_prev += tprev;
        m2_prev += tprev * tprev;

        m1_curr += tex2Dlod(sRELIGHT_M1Tex, i.uv + BUFFER_PIXEL_SIZE * 5.0 * float2(x, y), 0).rgb;
        m2_curr += tex2Dlod(sRELIGHT_M2Tex, i.uv + BUFFER_PIXEL_SIZE * 5.0 * float2(x, y), 0).rgb;
    } 

    m1_prev /= 9;
    m2_prev /= 9;
    m1_curr /= 9;
    m2_curr /= 9;

    float3 variance = max(0, m2_curr - m1_curr * m1_curr);
    float3 bias = (m1_curr - m1_prev);
    float3 sigma2_x = max(0, m2_prev - m1_prev * m1_prev);
    float3 sigma2_y = max(0, m2_curr - m1_curr * m1_curr);

    float3 denom = sigma2_x + sigma2_y + bias * bias;
    float3 alpha = denom < 0.0001.xxx ? 1.0.xxx : saturate(1 - sigma2_y / denom);
    alpha = dot(alpha, 1) - maxc(alpha) - minc(alpha);//median fixes weird colors
    alpha = clamp(alpha, 0.025, 0.5);
    o = float4(lerp(prev, curr, alpha), curr_gbuffer.w);
}

void BlendPS(in VSOUT i, out float3 o : SV_Target0)
{
    float3 c = tex2D(ColorInput, i.uv).rgb;
    float3 l = tex2D(sRELIGHT_Aux2, i.uv).rgb;
    float sss_culling_mask = tex2D(sRELIGHT_SSSCullingMask, i.uv).x;  
    float skinmask = skindetect(c, Depth::get_linear_depth(i.uv));
   
    l = lerp(l, 1, saturate(Depth::get_linear_depth(i.uv)));
    o = pack_hdr(l * unpack_hdr(c));

    if(USE_ALBEDO_ESTIMATION)
    {
        o = pack_hdr(unpack_hdr(c) * AMBIENT_INT * AMBIENT_INT + Deferred::get_albedo(i.uv) * l);
    }

    if(DEBUG_MODE == 1)
    {
        float2 scaled_uv = i.uv * 4.0;
        int2 layer = int2(scaled_uv);
        scaled_uv = frac(scaled_uv);

        if(layer.x == 0)
        {        
            o = layer.y == 0 ? Debug::viridis(Depth::get_linear_depth(scaled_uv)) 
            : layer.y == 1 ? pack_hdr(tex2Dlod(sRELIGHT_Aux2, scaled_uv, 0).rgb / 32.0)
            : layer.y == 2 ? Deferred::get_normals(scaled_uv) * 0.5 * float3(1,-1,-1) + 0.5
            : layer.y == 3 ? skindetect(tex2Dlod(ColorInput, scaled_uv, 0).rgb, Depth::get_linear_depth(scaled_uv))//step(0.5, tex2Dlod(sRELIGHT_SSSCullingMask, scaled_uv, 0).x)
            : o;
        }
    }
    else if(DEBUG_MODE == 2)
    {
        o = pack_hdr(l / 32.0);
    }
    else if(DEBUG_MODE == 3)
    {
        o = skinmask;
    }
}

void UpdatePrevBuffersPS0(in VSOUT i, out PSOUT2 o)
{
    if(SHADOW_MODE == 0) discard;
    
    o.t0 = tex2Dfetch(sRELIGHT_Aux2, uint2(i.vpos.xy));  //resolved light trace 
    o.t1 = float4(Deferred::get_normals(i.uv), Camera::depth_to_z(Depth::get_linear_depth(i.uv)));
}

/*=============================================================================
	Ingame Overlay
=============================================================================*/

float2 ray_sphere_intersection(float3 ray_origin, float3 raraydir, float3 sphere_center, float sphere_radius)
{
    float3 delta_vec = ray_origin - sphere_center;
    float b = dot(delta_vec, raraydir);
    float c = dot(delta_vec, delta_vec) - sphere_radius * sphere_radius;
    float h = b * b - c;
    float2 ret =  h < 0 ? 100000000 : -b + float2(-1, 1) * sqrt(h);
    ret = ret < 0.0.xx ? 100000000 : ret;
    return ret;
}

//by Inigo Quilez, MIT License
float ray_capsule_intersection( in float3 ro, in float3 rd, in float3 pa, in float3 pb, in float r )
{
    float3 ba = pb - pa;
    float3 oa = ro - pa;

    float baba = dot(ba,ba);
    float bard = dot(ba,rd);
    float baoa = dot(ba,oa);
    float rdoa = dot(rd,oa);
    float oaoa = dot(oa,oa);

    float a = baba      - bard*bard;
    float b = baba*rdoa - baoa*bard;
    float c = baba*oaoa - baoa*baoa - r*r*baba;
    float h = b*b - a*c;
    [branch]
    if( h>=0.0 )
    {
        float t = (-b-sqrt(h))/a;
        float y = baoa + t*bard;
        // body
        [flatten]if( y>0.0 && y<baba ) return t;
        // caps
        float3 oc = (y<=0.0) ? oa : ro - pb;
        b = dot(rd,oc);
        c = dot(oc,oc) - r*r;
        h = b*b - c;
        [flatten]if( h> 0.0 ) return -b - sqrt(h);
    }
    return 111111111;
}

float ray_cone_intersection(in float3 ro, in float3 rd, in float3 pa, in float3 pb, in float ra, in float rb)
{
    float3 ba = pb - pa;
    float3 oa = ro - pa;
    float3 ob = ro - pb;
    
    float m0 = dot(ba,ba);
    float m1 = dot(oa,ba);
    float m2 = dot(ob,ba); 
    float m3 = dot(rd,ba);

    float3 v0 = oa*m3-rd*m1;
    float3 v1 = ob*m3-rd*m2;
   
    //caps
    [branch]if(m1 < 0.0) 
    {         
        [flatten]if(dot(v0, v0) < (ra*ra*m3*m3)) 
        return -m1/m3; 
    }    
    // body
    float m4 = dot(rd,oa);
    float m5 = dot(oa,oa);
    float rr = ra - rb;
    float hy = m0 + rr*rr;
    
    float k2 = m0*m0    - m3*m3*hy;
    float k1 = m0*m0*m4 - m1*m3*hy + m0*ra*(rr*m3*1.0        );
    float k0 = m0*m0*m5 - m1*m1*hy + m0*ra*(rr*m1*2.0 - m0*ra);
    
    float h = k1*k1 - k2*k0;
    [flatten]
    if( h<0.0 ) return 111111111;

    float t = (-k1-sqrt(h))/k2;

    float y = m1 + t*m3;
    [flatten]
    if( y>0.0 && y<m0 ) 
    {
        return t;
    }
    
    return 111111111;
}

//xyz = normal, w = closest hit
float4 ray_sphere_intersection_with_normal(float3 ro, float3 rd, float3 sphere_center, float sphere_radius)
{
    float3 delta_vec = ro - sphere_center;
    float b = dot(delta_vec, rd);
    float c = dot(delta_vec, delta_vec) - sphere_radius * sphere_radius;
    float h = b * b - c;
    float2 t =  h < 0 ? 100000000 : -b + float2(-1, 1) * sqrt(h);
    t = t < 0.0.xx ? 100000000 : t;

    float3 hit = ro + rd * t.x;
    return float4(normalize(hit - sphere_center), t.x);
}

float4 ray_capsule_intersection_with_normal(float3 ro, float3 rd, float3 pa, float3 pb, float r)
{
    float3 ba = pb - pa;
    float3 oa = ro - pa;

    float baba = dot(ba,ba);
    float bard = dot(ba,rd);
    float baoa = dot(ba,oa);
    float rdoa = dot(rd,oa);
    float oaoa = dot(oa,oa);

    float a = baba      - bard*bard;
    float b = baba*rdoa - baoa*bard;
    float c = baba*oaoa - baoa*baoa - r*r*baba;
    float h = b*b - a*c;

    float mint = 100000000;
    [branch]
    if( h>=0.0 )
    {
        float t = (-b-sqrt(h))/a;
        float y = baoa + t*bard;

        [flatten]if( y>0.0 && y<baba ) 
        {
            mint = t;
        }
        else 
        {
            float3 oc = (y<=0.0) ? oa : ro - pb;
            b = dot(rd,oc);
            c = dot(oc,oc) - r*r;
            h = b*b - c;
            mint = h > 0.0 ? -b - sqrt(h) : mint;
        }        
    }

    float3 hit = ro + rd * mint;
    float u = saturate(dot(hit - pa, ba) / baba);
    float3 normal = (hit - pa - u * ba) / r;

    return float4(normal, mint);
}

float4 ray_cone_intersection_with_normal(float3 ro, float3 rd, float3 pa, float3 pb, float ra, float rb)
{
    float3  ba = pb - pa;
    float3  oa = ro - pa;
    float3  ob = ro - pb;
    
    float m0 = dot(ba,ba);
    float m1 = dot(oa,ba);
    float m2 = dot(ob,ba); 
    float m3 = dot(rd,ba);

    //caps
         if( m1<0.0 ) { if( dot2(oa*m3-rd*m1)<(ra*ra*m3*m3) ) return float4(-ba*rsqrt(m0), -m1/m3); }
    else if( m2>0.0 ) { if( dot2(ob*m3-rd*m2)<(rb*rb*m3*m3) ) return float4( ba*rsqrt(m0), -m2/m3); }
    
    // body
    float m4 = dot(rd,oa);
    float m5 = dot(oa,oa);
    float rr = ra - rb;
    float hy = m0 + rr*rr;
    
    float k2 = m0*m0    - m3*m3*hy;
    float k1 = m0*m0*m4 - m1*m3*hy + m0*ra*(rr*m3*1.0        );
    float k0 = m0*m0*m5 - m1*m1*hy + m0*ra*(rr*m1*2.0 - m0*ra);
    
    float h = k1*k1 - k2*k0;
    if(h<0.0) return 100000000;

    float t = (-k1-sqrt(h))/k2;

    float y = m1 + t*m3;
    if(y > 0.0 && y < m0) 
    {
        return float4(normalize(m0*(m0*(oa+t*rd)+rr*ba*ra)-ba*hy*y), t);
    }
    
    return 100000000;
}


void LightOverlayPS(in VSOUT i, out float3 o : SV_Target0)
{   
   // if(!OVERLAY_OPEN || SCREENSHOT || HIDE_LIGHT_SOURCES) discard;
    if((LIGHT_OVERLAY_BEHAVIOR == 0) ||
       (LIGHT_OVERLAY_BEHAVIOR == 1 && (!OVERLAY_OPEN || SCREENSHOT)) ||
       (LIGHT_OVERLAY_BEHAVIOR == 2 && !OVERLAY_OPEN)) discard;

    LightDesc lights[AMOUNT_OF_LIGHTS];  
    init_lights(lights);

    float3 color = tex2D(ColorInput, i.uv).rgb;

    float2 bayer[4] = 
    {
        float2(-0.5, -0.5),
        float2( 0.5, 0.5),
        float2(-0.5, 0.5),
        float2( 0.5, -0.5)
    };

    //tiny bit of temporal jitter for "TAA", with a high frequqnc
    i.uv += bayer[FRAMECOUNT % 4] * BUFFER_PIXEL_SIZE*0.6;
   
    //float4 lightvis = float4(0, 0, 0, RESHADE_DEPTH_LINEARIZATION_FAR_PLANE);
    float3 p = Camera::uv_to_proj(i.uv);
    float p_dist = length(p);
    float3 e = p / p_dist;

    float3 normal = 1;
    float min_t = 1e10;
    float3 lightcolor = 0;

    [loop]
    for(int id = 0; id < AMOUNT_OF_LIGHTS; id++)    
    {
        if(dot(lights[id].radiance, 1) == 0) continue;

        switch(lights[id].type)
        {
            case LIGHT_TYPE_INFINITE:
            {
                float3 centerpos = float3(0, 0, 0.5);
                float size = 0.1;
                float3 arrowheadpos = centerpos - lights[id].param0 * size;   
                float3 tippos = arrowheadpos - lights[id].param0 * 0.35 * size; 

                float4 intersect_head = ray_cone_intersection_with_normal(0, e, arrowheadpos, tippos, 0.1 * size, 0);
                float4 intersect_body = ray_capsule_intersection_with_normal(0, e, centerpos, arrowheadpos, 0.03333 * size);

                [flatten]
                if(intersect_head.w < min_t) 
                {
                    min_t = intersect_head.w;
                    normal = intersect_head.xyz;
                    lightcolor = lights[id].radiance;
                }
                [flatten]
                if(intersect_body.w < min_t) 
                {
                    min_t = intersect_body.w;
                    normal = intersect_body.xyz;
                    lightcolor = lights[id].radiance;
                }               

                break;
            }
            case LIGHT_TYPE_SPHERE:
            {
                float4 intersect_light = ray_sphere_intersection_with_normal(0, e, lights[id].param0, SPHERE_LIGHT_RADIUS_SCALE * lights[id].penumbra); 

                [flatten]
                if(intersect_light.w < min_t) 
                {
                    min_t = intersect_light.w;
                    normal = intersect_light.xyz;
                    lightcolor = lights[id].radiance;
                }

                break;
            }
        }
    }

    float3 closest_hit = e * min_t;

    float3 lightdir = normalize(float3(-1, 3, -0.5));
    lightcolor = normalize(lightcolor + 1e-5) * sqrt(length(lightcolor));

    //make them fancier
    float diff = abs(0.25+0.75*dot(normal, normalize(float3(0,-8,-1))));
    diff *= diff;
    diff = lerp(diff, 1, 0.05);    
    float rimlight = saturate(1 - dot(-e, normal));
    rimlight = pow(rimlight, 3);
    diff = lerp(diff, rimlight, 0.555);
    diff = lerp(diff, 1, 0.03);
    diff *= DEBUG_MODE != 2 ? 32 : 16; 

    color = lerp(color, pack_hdr(lightcolor * diff), (min_t < p_dist) * LIGHT_OVERLAY_OPACITY);
    o = color;
}

#if _COMPUTE_SUPPORTED

uint2 morton_idx_to_xy(uint idx)
{    
    uint2 pos = uint2(idx, idx >> 1);
    pos &= 0x55555555;   
    pos = (pos ^ (pos >> 1)) & 0x33333333; 
    pos = (pos ^ (pos >> 2)) & 0x0F0F0F0F; 
    pos = (pos ^ (pos >> 4)) & 0x00FF00FF; 
    pos = (pos ^ (pos >> 8)) & 0x0000FFFF;
    return pos;
}

groupshared float2 z_tgsm[32*32];

void SinglePassDownsampleCS(in CSIN i)
{
     //remap 32x32 threads to morton order
    i.dispatchthreadid.xy = i.groupid.xy * 32u + morton_idx_to_xy(i.threadid);

    //reducing 32x32 to 1x1 equals 32² -> 16² -> 8² -> 4² -> 2² -> 1² = 5 mipmaps
    //so to create 7 mipmaps, we need to downsample 2 times i.e. each thread needs to reduce 4x4 pixels first
    float2 local_minmax = 1e10; //min / max of thread-local 4x4 block. .y is negated to compute min directly

    [unroll]
    for(int quad = 0; quad < 4; quad++)
    {
        //repeat logic inside the 4x4 block, i.e. order pixels by morton index
        //here we tex2Dgather each 2x2 subblock, but for a regular reduce pass, they'd be sampled directly
        uint2 quad_offset = morton_idx_to_xy(quad);
        uint2 global_pos = i.dispatchthreadid.xy * 4 + quad_offset * 2;

        float2 quad_topleft_uv = saturate((global_pos + 0.5) * BUFFER_PIXEL_SIZE);
        float2 corrected_uv = Depth::correct_uv(quad_topleft_uv);
        corrected_uv.y -= BUFFER_PIXEL_SIZE.y * 0.5;    //shift upwards since gather looks down and right

#if RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN
    corrected_uv.y -= BUFFER_PIXEL_SIZE.y * 0.5;    //shift upwards since gather looks down and right
    float4 quad_texels = tex2DgatherR(DepthInput, corrected_uv).wzyx;  
#else
    float4 quad_texels = tex2DgatherR(DepthInput, corrected_uv);
#endif
        quad_texels = Depth::linearize(quad_texels);
        //gather order is wack      
        
        quad_texels.w = Camera::depth_to_z(quad_texels.w);       
        tex2Dstore(stRELIGHT_HiZMipChain0, global_pos + uint2(0, 0), quad_texels.w);
        quad_texels.x = Camera::depth_to_z(quad_texels.x);
        tex2Dstore(stRELIGHT_HiZMipChain0, global_pos + uint2(0, 1), quad_texels.x);
        quad_texels.z = Camera::depth_to_z(quad_texels.z);
        tex2Dstore(stRELIGHT_HiZMipChain0, global_pos + uint2(1, 0), quad_texels.z);
         quad_texels.y = Camera::depth_to_z(quad_texels.y);
        tex2Dstore(stRELIGHT_HiZMipChain0, global_pos + uint2(1, 1), quad_texels.y);

        //if we were doing a regular single pass downsample, we could skip everything until here, where we reduce the 2x2 quad and write it

        float2 quad_minmax = float2(minc(quad_texels), maxc(quad_texels));
        tex2Dstore(stRELIGHT_HiZMipChain1, global_pos / 2, quad_minmax.xyxy);

        local_minmax = min(local_minmax, float2(quad_minmax.x, -quad_minmax.y));
    }

    tex2Dstore(stRELIGHT_HiZMipChain2, i.dispatchthreadid.xy, float4(local_minmax, 0, 0));
    z_tgsm[i.threadid] = local_minmax;
    barrier();

    if(!(i.threadid & 3))
    {
        [unroll]for(int j = 1; j < 4; j++) local_minmax = min(local_minmax, z_tgsm[i.threadid + j * 1]);
        tex2Dstore(stRELIGHT_HiZMipChain3, i.dispatchthreadid.xy / 2, float4(local_minmax, 0, 0));
        z_tgsm[i.threadid] = local_minmax;
    }
    barrier();
    if(!(i.threadid & 15))
    {
        [unroll]for(int j = 1; j < 4; j++) local_minmax = min(local_minmax, z_tgsm[i.threadid + j * 4]);        
        tex2Dstore(stRELIGHT_HiZMipChain4, i.dispatchthreadid.xy / 4, float4(local_minmax, 0, 0));
        z_tgsm[i.threadid] = local_minmax;
    }
    barrier();
    if(!(i.threadid & 63))
    {
        [unroll]for(int j = 1; j < 4; j++) local_minmax = min(local_minmax, z_tgsm[i.threadid + j * 16]);
        tex2Dstore(stRELIGHT_HiZMipChain5, i.dispatchthreadid.xy / 8, float4(local_minmax, 0, 0));
        z_tgsm[i.threadid] = local_minmax;
    }
    barrier();
    if(!(i.threadid & 255))
    {
        [unroll]for(int j = 1; j < 4; j++) local_minmax = min(local_minmax, z_tgsm[i.threadid + j * 64]);
        tex2Dstore(stRELIGHT_HiZMipChain6, i.dispatchthreadid.xy / 16, float4(local_minmax, 0, 0));
        z_tgsm[i.threadid] = local_minmax;
    }
    barrier();
    if(!(i.threadid & 1023))
    {
        [unroll]for(int j = 1; j < 4; j++) local_minmax = min(local_minmax, z_tgsm[i.threadid + j * 256]);        
        tex2Dstore(stRELIGHT_HiZMipChain7, i.dispatchthreadid.xy / 32, float4(local_minmax, 0, 0));
        //z_tgsm[i.threadid] = local_minmax;
    }
    //barrier();
}
#endif

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_RELIGHT
<
    ui_label = "iMMERSE Ultimate: ReLight";
    ui_tooltip =        
        "                                MartysMods - ReLight                              \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "ReLight adds custom light sources with raytraced shadows to your scene, allowing you\n"
        "to either accentuate the picture or completely re-light the scene.                \n"
        "\n"
        "ReLight is designed for screenshots, and is not recommended for gameplay use!     \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n";
>
{
    
#if _COMPUTE_SUPPORTED
    pass 
    { 
        ComputeShader = SinglePassDownsampleCS<32, 32>;
        DispatchSizeX = CEIL_DIV(BUFFER_WIDTH, 32 * 4); 
        DispatchSizeY = CEIL_DIV(BUFFER_HEIGHT, 32 * 4);
        GenerateMipMaps = false;
    }
#endif   
    pass { VertexShader = MainVS; PixelShader = ZWritePS;  RenderTarget = RELIGHT_ZBuffer;}  
    pass { VertexShader = MainVS; PixelShader = AlbedoWritePS; RenderTarget0 = RELIGHT_RadianceTex; }    
    pass { VertexShader = MainVS; PixelShader = TraceLightsPS; RenderTarget = RELIGHT_Aux0;}  

    pass { VertexShader = SubsurfaceScatteringVS; PixelShader = SubsurfaceCullingMaskPS; RenderTarget = RELIGHT_SSSCullingMask;} 
    pass { VertexShader = SubsurfaceScatteringVS; PixelShader = SubsurfacePathtracePS; RenderTarget = RELIGHT_SSSRaw; ClearRenderTargets = true;} //such that discard doesn't leave stale data
    pass { VertexShader = SubsurfaceScatteringVS; PixelShader = SubsurfaceDenoisePS; RenderTarget = RELIGHT_Aux0; BlendEnable = true; SrcBlend = ONE; DestBlend = ONE; BlendOp = ADD;}    
   
    pass { VertexShader = MainVS; PixelShader = SecondMomentPS; RenderTarget0 = RELIGHT_M1Tex; RenderTarget1 = RELIGHT_M2Tex;}
    pass { VertexShader = MainVS; PixelShader = TemporalFilterPS; RenderTarget = RELIGHT_Aux2;}
    pass { VertexShader = MainVS; PixelShader = UpdatePrevBuffersPS0;  RenderTarget0 = RELIGHT_Aux1; RenderTarget1 = RELIGHT_GBufferPrev;}
    pass { VertexShader = MainVS; PixelShader = BlendPS; }
    pass { VertexShader = MainVS; PixelShader = LightOverlayPS; }
}