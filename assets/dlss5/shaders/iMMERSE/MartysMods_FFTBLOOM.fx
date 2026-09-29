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

    Convolution Bloom

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/

/*=============================================================================
	Preprocessor settings
=============================================================================*/

#ifndef CONVOLUTION_BLOOM_QUALITY
 #define CONVOLUTION_BLOOM_QUALITY          1 //0 to 2, 0 lowest, 2 highest
#endif 

#ifndef CONVOLUTION_BLOOM_MASK_PRESET 
 #define CONVOLUTION_BLOOM_MASK_PRESET      0 //different mask types, each with their own sliders
#endif

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform float CONVOLUTION_BLOOM_PADDING <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 0.5;
	ui_label = "Bloom Padding";
    ui_tooltip = "FFT based bloom causes a wrap-around effect, i.e. if the glow crosses the screen boundary\n"
                 "it will appear on the opposite side of the screen. Creating a black border in the buffers\n"
                 "migitates this problem but lowers effective resolution. Raise this to add padding.\n";
> = 0.0;

uniform float HDR_EXPOSURE <
	ui_type = "drag";
	ui_min = -5.0; ui_max = 5.0;
	ui_label = "Log Exposure Bias";
> = 0.0;

uniform float HDR_WHITEPOINT <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 12.0;
    ui_label = "Log HDR Whitepoint";
> = 7.0;

uniform float HDR_BLOOM_INT <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Bloom Intensity";
> = 0.3;

#if CONVOLUTION_BLOOM_MASK_PRESET == 0
uniform int CURR_PRESET_INFO <ui_type = "radio";ui_label = " ";ui_text ="\nBloom Preset: Diffraction Spikes";>;
uniform int FFTBLOOM_MASK_PRESET_0_NUM_SPIKES < ui_type = "slider"; ui_min = 1; ui_max = 7; ui_step = 1; ui_label = "Diffraction Spike Amount"; > = 3;
uniform float FFTBLOOM_MASK_PRESET_0_ROTATION < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Diffraction Spike Rotation"; > = 0.5;
uniform float FFTBLOOM_MASK_PRESET_0_RADIUS < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Diffraction Spike Radius"; > = 0.0;
uniform float FFTBLOOM_MASK_PRESET_0_WIDTH < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Diffraction Spike Blurryness"; > = 0.0;
uniform float FFTBLOOM_MASK_PRESET_0_SPREAD < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Diffraction Spike Spread"; > = 0.0;
uniform float FFTBLOOM_MASK_PRESET_0_RATIO < ui_type = "drag"; ui_min = -1.0; ui_max = 1.0; ui_label = "Diffraction Spike Ratio"; > = 0.0;

#elif CONVOLUTION_BLOOM_MASK_PRESET == 1 
uniform int CURR_PRESET_INFO <ui_type = "radio";ui_label = " ";ui_text ="\nBloom Preset: Inverse Square Glow";>;
uniform float FFTBLOOM_MASK_PRESET_1_RADIUS < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Glow Radius"; > = 1.0;
uniform float FFTBLOOM_MASK_PRESET_1_GLARE < ui_type = "drag"; ui_min = 0.0; ui_max = 1.0; ui_label = "Glare Intensity"; > = 0.0;
#endif

uniform int FFTBLOOM_DEBUG_VIEW <
	ui_type = "combo";
    ui_label = "Enable Debug View";
	ui_items = "None\0Bloom Only\0Mask Texture\0";
	ui_tooltip = "Different debug outputs";
    ui_category = "Debug";
> = 0;

uniform int UIHELP <
	ui_type = "radio";
	ui_label = " ";	
	ui_text ="\nDescription for preprocessor definitions:\n"
	"\n"
	"CONVOLUTION_BLOOM_QUALITY (0-2)\n"
	"\n"
	"Resolution of internal fourier transform kernel. Higher values\n"
    "produce sharper results, at the cost of performance.    \n"
	"\n"
	"CONVOLUTION_BLOOM_MASK_PRESET (0-1)\n"
	"\n"
	"Different presets for procedural bloom mask shapes.\n"
	"Each comes with its own set of tweakables.\n\n"
	"0: Diffraction Spikes\n"
	"1: Inverse Square Glow\n";
	ui_category_closed = false;
>;
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
*/
/*=============================================================================
	Textures, Samplers, Globals, Structs
=============================================================================*/

texture ColorInputTex : COLOR;
sampler ColorInput 	{ Texture = ColorInputTex;};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_math.fxh"
#include ".\MartysMods\mmx_qmc.fxh"
#include ".\MartysMods\mmx_texture.fxh"
#include ".\MartysMods\mmx_hash.fxh"

#if CONVOLUTION_BLOOM_QUALITY == 0 
 #define FFT_SIZE_X 1024
 #define FFT_SIZE_Y 512
#elif CONVOLUTION_BLOOM_QUALITY == 1
 #define FFT_SIZE_X 2048
 #define FFT_SIZE_Y 1024
#else 
 #define FFT_SIZE_X 4096
 #define FFT_SIZE_Y 2048
#endif

#if FFT_SIZE_X == 2 || FFT_SIZE_X == 32 || FFT_SIZE_X == 128 || FFT_SIZE_X == 2048
	#define RADIX_X     2
#elif FFT_SIZE_X == 4 || FFT_SIZE_X == 16 || FFT_SIZE_X == 256 || FFT_SIZE_X == 1024
	#define RADIX_X     4
#elif FFT_SIZE_X == 8 || FFT_SIZE_X == 64 || FFT_SIZE_X == 512 || FFT_SIZE_X == 4096
    #define RADIX_X     8
#else 
    #error "Undefined Radix Size"
#endif

#if FFT_SIZE_Y == 2 || FFT_SIZE_Y == 32 || FFT_SIZE_Y == 128 || FFT_SIZE_Y == 2048
	#define RADIX_Y     2
#elif FFT_SIZE_Y == 4 || FFT_SIZE_Y == 16 || FFT_SIZE_Y == 256 || FFT_SIZE_Y == 1024
	#define RADIX_Y     4
#elif FFT_SIZE_Y == 8 || FFT_SIZE_Y == 64 || FFT_SIZE_Y == 512 || FFT_SIZE_Y == 4096
    #define RADIX_Y     8
#else 
    #error "Undefined Radix Size"
#endif

#define GROUP_SIZE_X (FFT_SIZE_X / RADIX_X)
#define GROUP_SIZE_Y (FFT_SIZE_Y / RADIX_Y)

texture ConvolutionBloomFFTTex { Width = FFT_SIZE_X; Height = FFT_SIZE_Y; Format = RGBA32F;  }; 
sampler sConvolutionBloomFFTTex { Texture = ConvolutionBloomFFTTex; };
storage stConvolutionBloomFFTTex { Texture = ConvolutionBloomFFTTex; };

texture ConvolutionBloomFFTTex2 { Width = FFT_SIZE_X; Height = FFT_SIZE_Y; Format = RGBA32F;  }; 
sampler sConvolutionBloomFFTTex2 { Texture = ConvolutionBloomFFTTex2; AddressU = WRAP; AddressV = WRAP;};
storage stConvolutionBloomFFTTex2 { Texture = ConvolutionBloomFFTTex2; };

texture ConvolutionBloomMaskTex { Width = FFT_SIZE_X; Height = FFT_SIZE_Y; Format = RG32F;  MipLevels = 1 + LOG2(FFT_SIZE_Y);}; 
sampler sConvolutionBloomMaskTex { Texture = ConvolutionBloomMaskTex;  };
storage stConvolutionBloomMaskTex { Texture = ConvolutionBloomMaskTex; };

texture ConvolutionBloomMaskTex2 { Width = FFT_SIZE_X; Height = FFT_SIZE_Y; Format = RG32F;  MipLevels = 1 + LOG2(FFT_SIZE_Y);}; 
sampler sConvolutionBloomMaskTex2 { Texture = ConvolutionBloomMaskTex2;  };
storage stConvolutionBloomMaskTex2 { Texture = ConvolutionBloomMaskTex2; };

texture ConvolutionBloomMaskNormFactorTex { Width = 1; Height = 1; Format = R32F;  }; 
sampler sConvolutionBloomMaskNormFactorTex { Texture = ConvolutionBloomMaskNormFactorTex; };

texture2D FFTBloomStateHashTex { Format = R32U;  }; 
sampler2D<uint> sFFTBloomStateHashTex { Texture = FFTBloomStateHashTex;  };
storage2D<uint> stFFTBloomStateHashTex { Texture = FFTBloomStateHashTex; };

texture2D FFTBloomRequestUpdateTex { Format = R8;  }; 
sampler2D sFFTBloomRequestUpdateTex { Texture = FFTBloomRequestUpdateTex;  };
storage2D stFFTBloomRequestUpdateTex { Texture = FFTBloomRequestUpdateTex; };

uniform uint  FRAMECOUNT  < source = "framecount"; >;
uniform int ACTIVE_VARIABLE < source = "overlay_active"; >;

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

//The ONLY way I found to ensure that ReShade doesn't manage to change the settings without the shader updating the mask
void HashStateCS(in CSIN i)
{
    uint hash = CURR_PRESET_INFO;
#if CONVOLUTION_BLOOM_MASK_PRESET == 0
    Hash::hash_combine(hash, FFTBLOOM_MASK_PRESET_0_NUM_SPIKES);
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_0_ROTATION));
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_0_RADIUS));
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_0_WIDTH));
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_0_SPREAD));
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_0_RATIO));
#else 
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_1_RADIUS));
    Hash::hash_combine(hash, asuint(FFTBLOOM_MASK_PRESET_1_GLARE));
#endif

    uint prev_hash = tex2Dfetch(stFFTBloomStateHashTex, 0).x;

    if(prev_hash != hash)
    {
        tex2Dstore(stFFTBloomStateHashTex, int2(0, 0), hash);
        tex2Dstore(stFFTBloomRequestUpdateTex, int2(0, 0), 1.0);
    }
    else 
    {
        tex2Dstore(stFFTBloomRequestUpdateTex, int2(0, 0), 0.0);
    }
}

bool mask_needs_updating()
{
    return tex2Dfetch(sFFTBloomRequestUpdateTex, 0).x > 0.5;
}

float3 cone_overlap(float3 c)
{
    float k = 0.4 * 0.33;
    float2 f = float2(1 - 2 * k, k);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

float3 cone_overlap_inv(float3 c)
{
    float k = 0.4 * 0.33;
    float2 f = float2(k - 1, k) * rcp(3 * k - 1);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

float3 inverse_tonemap(float3 x, float w)
{
    const float k = 2.0;
    return x * pow((1.0 + pow(w, -k)) - pow(x, k), -1.0 / k);
}

float3 tonemap(float3 x, float w)
{
    const float k = 2.0;
    return pow(1 + pow(w, -k), 1.0 / k) * x * pow(1.0 + pow(x, k), -1.0 / k);
}

float3 sdr_to_hdr(float3 c, float w)
{ 
    c = cone_overlap(c);
    c *= c;
    float a = 1 + exp2(-w);    
    c = c / (a - c); 
    return c;
}

float3 hdr_to_sdr(float3 c, float w)
{   
    float a = 1 + exp2(-w); 
    c = a * c * rcp(1 + c);
    c = sqrt(c);
    c = cone_overlap_inv(c);
    return c;
}

float2 complex_conj(float2 z)
{
    return float2(z.x, -z.y);
}

float2 complex_mul(float2 c1, float2 c2)
{
#if 0 //normal
    return float2(c1.x * c2.x - c1.y * c2.y,                   
                  c1.y * c2.x + c1.x * c2.y);   
#else //gauss - maybe influences precision?
    float2 z = c1 * c2;
    return float2(z.x - z.y, dot(c1 * c2.yx, 1));
 #endif
}

//scales UV to fit target ratio (will create border)
float2 scale_uv_fit(float2 uv, float source, float dest)
{
    float4 scalemad;
    scalemad.xy = source < dest ? float2(dest / source, 1) : float2(1, source / dest);
    scalemad.zw = 0.5 - 0.5 * scalemad.xy;
    return uv * scalemad.xy + scalemad.zw; 
}

//scales UV to fit target ratio (will crop)
float2 scale_uv_crop(float2 uv, float source, float dest)
{
    float4 scalemad;
    scalemad.xy = source > dest ? float2(dest / source, 1) : float2(1, source / dest);
    scalemad.zw = 0.5 - 0.5 * scalemad.xy;
    return uv * scalemad.xy + scalemad.zw; 
}

//should move this to math.fxh I guess...
float fastatan2(float y, float x)
{ 
    float cosatan2 = x * rcp(abs(x) + abs(y));     
    float t = HALF_PI - cosatan2 * HALF_PI;
    return y < 0.0 ? -t : t;
}

float bessel_J1(float x)
{
    #if 1    
    float x2 = x * x;
    //float a = (0.1601 * x2 + 0.866) * sin(x) / ((1 + 0.3489 * x2) * sqrt(sqrt(1 + 0.4181 * x2)));
    //float b = x * (0.1007 * x2 + 0.3718) * cos(x) / (pow(1 + 0.4181 * x2, 0.75) * (1 + 0.3489 * x2));
    // return a - b;
    float c0 = mad(0.1601, x2, 0.866);
    float c1 = mad(0.3489, x2, 1);
    float c2 = log2(mad(0.4181, x2, 1));
    float c3 = mad(0.1007, x2, 0.3718);
    float2 sc; sincos(x, sc.x, sc.y);
    float a = c0 * exp2(c2 * -0.25) * sc.x;
    float b = c3 * exp2(c2 * -0.75) * (sc.y * x);
    return (a - b) * rcp(c1);  
    #else 
    return 6 * sin(x) / (abs(x) + 10);
    #endif
}

float sinc(float x)
{
    return abs(x) < 1e-5 ? 1 : sin(x) / x;
}  

float upper_sinc(float x)
{
    float softlim = x / pow(1 + pow(abs(x / HALF_PI), 4.0), 0.25);
    return abs(x) < 1e-5 ? 1 : sin(softlim) / x;
}

uint J(uint i) 
{
    return reversebits(i);
}

uint P(uint v) 
{                                                 // Input is a bit-reversed uint32_t
    v ^=  v                << 16;
    v ^= (v & 0x00FF00FFu) <<  8;
    v ^= (v & 0x0F0F0F0Fu) <<  4;
    v ^= (v & 0x33333333u) <<  2;
    v ^= (v & 0x55555555u) <<  1;
    return v;
}

uint JPJ(uint v) 
{                                
    v ^=  v                >> 16;
    v ^= (v & 0xFF00FF00u) >>  8;
    v ^= (v & 0xF0F0F0F0u) >>  4;
    v ^= (v & 0xCCCCCCCCu) >>  2;
    v ^= (v & 0xAAAAAAAAu) >>  1;
    return v;
}

//PG: replaced (v & (0xFFFFFFFFu >> m)) with (v << m) >> m 
//as the former expression seems to be buggy?

uint JPJ(uint v, int m) 
{
    // Scramble leading m bits by    
    return (JPJ(v >> (32 - m)) << (32 - m)) | ((v << m) >> m);       
}

uint G(uint x, int m) 
{
    uint v = JPJ(x >> (32 - m));
    v ^=  v >> 1;
    // Inverse of lower LP matrix
    return (v << (32 - m)) | ((x << m) >> m);
}

void optimize_discrepancy(inout uint2 p, int m)
{
    p.x =   G(p.x, m);
    p.y = JPJ(p.y, m);
}

float2 sobol(uint i)
{
    uint x = J(i);
    uint y = P(i);
    uint2 p = uint2(J(i), P(i));
    optimize_discrepancy(p, 32);
    return float2(x, y) * exp2(-32.0);
}


float create_mask(float2 uv)
{    
#if CONVOLUTION_BLOOM_MASK_PRESET == 0    
    int num_blades = FFTBLOOM_MASK_PRESET_0_NUM_SPIKES;

    float2 baseuv = uv * 2 - 1;
    baseuv *= saturate(float2(1, -1) * FFTBLOOM_MASK_PRESET_0_RATIO) * 2 + 1;
    baseuv = Math::rotate_2D(baseuv, Math::get_rotator(TAU / num_blades * FFTBLOOM_MASK_PRESET_0_ROTATION * 0.5 * 0.5));    
    float r = length(baseuv);        
    float2 normuv = baseuv / r;

    float t0 = r * rcp(1 + r / saturate(1 - pow(saturate(FFTBLOOM_MASK_PRESET_0_WIDTH), 0.05)*0.9999));
    
    float mask = 0;
    [loop]
    for(int j = 0; j < num_blades; j++)
    {
        [unroll]
        for(int k = 0; k < 32; k++)
        {
            float2 jitter = sobol(j * num_blades + k);
            float phi = (j + (jitter.x - 0.5) * FFTBLOOM_MASK_PRESET_0_SPREAD) * TAU / num_blades * 0.5;
            float2 dir; sincos(phi, dir.x, dir.y);  

            float X = dot(normuv, dir);
            float v = (jitter.y + 0.1) * 2000.0 * X * t0;
            mask += (bessel_J1(v) / v);
        }            
    }

    mask *= upper_sinc(r * exp2(10 - 10*FFTBLOOM_MASK_PRESET_0_RADIUS));
    mask *= mask; 
    return mask;
#elif CONVOLUTION_BLOOM_MASK_PRESET == 1
    uv = uv * 2.0 - 1.0;
    float r = length(uv); 
    float phi = fastatan2(uv.y, uv.x);  
    float falloff = rcp(0.0001 + r);
    //fake limit, inverse square "radius" is limited only by its intensity when integral normalized but try to explain that to users...
    falloff = max(0, falloff - 1.0 / (0.01 + FFTBLOOM_MASK_PRESET_1_RADIUS * 4.0)); 
    falloff *= falloff;
    falloff *= lerp(1, frac(sin(phi * 33.0) + phi * 19.0), FFTBLOOM_MASK_PRESET_1_GLARE);
    return falloff;
#endif   
}

/*=============================================================================
	Shader Entry Points
=============================================================================*/

//2 channel passes, forward only for mask

#define FFT_WORKING_SIZE        FFT_SIZE_X
#define FFT_RADIX               RADIX_X
#define FFT_INSTANCE            FFTSingleX 
#define FFT_AXIS                0 //X
#define FFT_CHANNELS            2

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassMaskXCS(in CSIN i)
{
    if(!mask_needs_updating()) return;
    FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomMaskTex, stConvolutionBloomMaskTex2, true);
}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

#define FFT_WORKING_SIZE        FFT_SIZE_Y
#define FFT_RADIX               RADIX_Y
#define FFT_INSTANCE            FFTSingleY
#define FFT_AXIS                1 //Y
#define FFT_CHANNELS            2

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassMaskYCS(in CSIN i)
{
    if(!mask_needs_updating()) return;
    FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomMaskTex2, stConvolutionBloomMaskTex, true);
}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

//4 channels parallel 2 and 2 both forward and backward

#define FFT_WORKING_SIZE        FFT_SIZE_X
#define FFT_RADIX               RADIX_X
#define FFT_INSTANCE            FFTDoubleX 
#define FFT_AXIS                0 //X
#define FFT_CHANNELS            4

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassMainForwardXCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomFFTTex, stConvolutionBloomFFTTex2, true);}
void FourierPassMainInverseXCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomFFTTex2, stConvolutionBloomFFTTex, false);}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

#define FFT_WORKING_SIZE        FFT_SIZE_Y
#define FFT_RADIX               RADIX_Y
#define FFT_INSTANCE            FFTDoubleY 
#define FFT_AXIS                1 //Y
#define FFT_CHANNELS            4

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassMainForwardYCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomFFTTex2, stConvolutionBloomFFTTex, true);}
void FourierPassMainInverseYCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sConvolutionBloomFFTTex, stConvolutionBloomFFTTex2, false);}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv);
    return o;
}

float lanczos2( float x )
{  
    //normalized sinc can be approximated with prod[i=1->N] 1 - x²/i²
    //and since lanczos2 uses 2 times sinc, once with half the phase, most of the terms
    //occur twice, so they can be squared at the end.

    //this is visually indistinguishable from real lanczos, meanwhile 33% faster
    float t = saturate(x * x * 0.25);//mul, mul_sat
    float res = 1 - 4.0/9.0 * t;//mad
    res = res - res * t;//mad
    res *= res;//mul
    res = res - res * t; //mad
    res *= 1 - 4 * t;//mad, mul
    return res;
    //const float tau = 2.0;
    //return abs(x) > 2.0 ? 0.0 : sinc(x / tau) * sinc(x);
}

void BloomSetupPS(in VSOUT i, out float4 o : SV_Target0) 
{    
    float2 target_texelsize = rcp(tex2Dsize(sConvolutionBloomFFTTex2).xy);

    //left ends up being at 1800.6 texels, right ends up at 1804.9 texels
    //40% left texel, 60% right

    float2 uv_lo = i.uv - target_texelsize * 0.5;
    float2 uv_hi = i.uv + target_texelsize * 0.5;

    uv_lo = scale_uv_fit(uv_lo, BUFFER_ASPECT_RATIO.y, 2.0);
    uv_hi = scale_uv_fit(uv_hi, BUFFER_ASPECT_RATIO.y, 2.0);
    uv_lo = (uv_lo - 0.5) / (1 - CONVOLUTION_BLOOM_PADDING) + 0.5;
    uv_hi = (uv_hi - 0.5) / (1 - CONVOLUTION_BLOOM_PADDING) + 0.5;

    float2 fractional_texelpos_lo = uv_lo * BUFFER_SCREEN_SIZE;
    float2 fractional_texelpos_hi = uv_hi * BUFFER_SCREEN_SIZE;

    float2 scaling = (fractional_texelpos_hi - fractional_texelpos_lo);
    int2 dst_texel = int2(i.vpos.xy);

    int2 kernelsize = ceil(scaling*2.0);
    kernelsize = min(kernelsize, 10);
    float2 src_texel_center = (fractional_texelpos_lo + fractional_texelpos_hi)*0.5 - 0.5;

    float2 src_texel;
    float2 otdtc;
    float2 w;
  
    o = 0;

    [loop]
    for(int y = -kernelsize.y; y < kernelsize.y; y++)
    {
        src_texel.y = floor(src_texel_center.y) + y;
        otdtc.y = abs(src_texel.y - src_texel_center.y) / scaling.y;
        w.y = lanczos2(otdtc.y);

        [loop]
        for(int x = -kernelsize.x; x < kernelsize.x; x++)
        {            
            src_texel.x = floor(src_texel_center.x) + x;
            otdtc.x = abs(src_texel.x - src_texel_center.x) / scaling.x;
            w.x = lanczos2(otdtc.x);            
            float ww = w.x * w.y; 

            if(abs(ww) < 0.25) //quick and dirty optimization that gets the cost down
                continue;

            float3 t = tex2Dfetch(ColorInput, src_texel).rgb;    
            t = sdr_to_hdr(t, HDR_WHITEPOINT);
            o += float4(t, 1) * ww;
        } 
    } 

    o.rgb /= o.w;
    o.rgb = max(o.rgb, 0); //lanczos can produce negative numbers
    o *= Math::inside_screen(i.uv);
    o.rgb *= exp2(HDR_EXPOSURE); 
    o.w = 1;
}

void MaskSetupPS(in VSOUT i, out float o : SV_Target0) 
{   
    if(!mask_needs_updating()) discard;
    i.uv = scale_uv_fit(i.uv, 1.0, 2.0);
    o = create_mask(i.uv);    
}

void MaskNormalizePS(in VSOUT i, out float o : SV_Target0) 
{
    if(!mask_needs_updating()) discard;
    o = rcp(tex2Dlod(sConvolutionBloomMaskTex, 0.5.xx, 100.0).x * sqrt(FFT_SIZE_X * FFT_SIZE_Y));//Sqrt here because we did that in the passes before as well
}

void ConvolveWithAlphaPS(in VSOUT i, out float4 o : SV_Target0) 
{
    float2 mask_fft = tex2Dfetch(sConvolutionBloomMaskTex, i.vpos.xy).xy;     
    float norm_factor = tex2Dfetch(sConvolutionBloomMaskNormFactorTex, 0).x;

    mask_fft *= norm_factor; //normalize here or the data will lose too much precision during the inverse transform

    float4 Zk       = tex2D(sConvolutionBloomFFTTex, i.uv);    
    float4 ZNminusk = tex2D(sConvolutionBloomFFTTex, 1 - i.uv);

    float2 fft_r = 0.5 * (Zk.xy + ZNminusk.xy);
    float2 fft_g = -0.5 * (Zk.xy - ZNminusk.xy);
    float2 fft_b = 0.5 * (Zk.zw + ZNminusk.zw);
    float2 fft_a = -0.5 * (Zk.zw - ZNminusk.zw);

    fft_r = complex_mul(fft_r, mask_fft);
    fft_g = complex_mul(fft_g, mask_fft);
    fft_b = complex_mul(fft_b, mask_fft);
    fft_a = complex_mul(fft_a, mask_fft);    

    o = float4(fft_r - fft_g, fft_b - fft_a);
}

void BlendPS(in VSOUT i, out float3 o : SV_Target0)
{   
    float2 read_uv = scale_uv_crop(i.uv, 2.0, BUFFER_ASPECT_RATIO.y);
    read_uv = (read_uv - 0.5) * (1 - CONVOLUTION_BLOOM_PADDING) + 0.5;
    //read_uv = frac(read_uv + 0.5);
    read_uv += 0.5;
    read_uv -= rcp(tex2Dsize(sConvolutionBloomFFTTex).xy) * 0.5; //not sure why I need this, I must be doing some offset slightly wrong...
    
    float3 bloom = Texture::sample2D_bspline_auto(sConvolutionBloomFFTTex2, read_uv).rgb;

    //bloom *= exp2(-HDR_WHITEPOINT * 0.25); //visually normalize so observed bloom intensity is agnostic of whitepoint setting    
    float3 col = tex2D(ColorInput, i.uv).rgb;

    col = sdr_to_hdr(col, HDR_WHITEPOINT);    
    col *= exp2(HDR_EXPOSURE); 
    // col += lerp(col, 0.05, HDR_BLOOM_HAZYNESS * 0.5 + 0.5) * bloom.rgb * HDR_BLOOM_INT * HDR_BLOOM_INT * 128.0;
    col = lerp(col, bloom, HDR_BLOOM_INT);
    
    if(FFTBLOOM_DEBUG_VIEW == 1) col = bloom.rgb;

    col = hdr_to_sdr(col, HDR_WHITEPOINT);
    o = saturate(col);

    if(FFTBLOOM_DEBUG_VIEW == 2)
    {
        float2 mask_aabb = 0.5 + (i.uv - 0.5) * BUFFER_ASPECT_RATIO.yx;

        if(Math::inside_screen(mask_aabb))
        {
            float mask = create_mask(mask_aabb);
            float normfact = tex2Dfetch(sConvolutionBloomMaskNormFactorTex, 0).x;
            mask *= normfact;
            mask *= 1000.0;
            mask /= 1.0 + mask;
            o = mask;
        }
    }
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_ConvolutionBloom
<
    ui_label = "iMMERSE Ultimate: ConvolutionBloom";
    ui_tooltip =        
        "                           MartysMods - Convolution Bloom                         \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "The convolution bloom is a high end bloom effect which leverages the fast fourier\n"
        "transform (FFT) of the image. This allows for completely customizable bloom shapes\n"
        "at a constant performance cost.                                                   \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n";
>
{
    pass {ComputeShader = HashStateCS<1, 1>; DispatchSizeX = 1; DispatchSizeY = 1; } 
    pass MaskSetup          {VertexShader = MainVS;   PixelShader = MaskSetupPS; RenderTarget = ConvolutionBloomMaskTex; }
    pass MaskNormalize      {VertexShader = MainVS;  PixelShader = MaskNormalizePS; RenderTarget = ConvolutionBloomMaskNormFactorTex; }
    pass MaskFFTX           {ComputeShader = FourierPassMaskXCS<GROUP_SIZE_X, 1>; DispatchSizeX = 1; DispatchSizeY = FFT_SIZE_Y; } //reads MaskTex, writes MaskTex2
    pass MaskFFTY           {ComputeShader = FourierPassMaskYCS<1, GROUP_SIZE_Y>; DispatchSizeX = FFT_SIZE_X; DispatchSizeY = 1; } //reads MaskTex2, writes MaskTex

    pass BloomSetup         {VertexShader = MainVS;   PixelShader = BloomSetupPS; RenderTarget = ConvolutionBloomFFTTex; } 
    pass BloomFFTX          {ComputeShader = FourierPassMainForwardXCS<GROUP_SIZE_X, 1>; DispatchSizeX = 1; DispatchSizeY = FFT_SIZE_Y; } //ConvolutionBloomFFTTex -> ConvolutionBloomFFTTex2
    pass BloomFFTY          {ComputeShader = FourierPassMainForwardYCS<1, GROUP_SIZE_Y>; DispatchSizeX = FFT_SIZE_X; DispatchSizeY = 1; } //ConvolutionBloomFFTTex2 -> ConvolutionBloomFFTTex
    pass MaskConvolve       {VertexShader = MainVS;   PixelShader = ConvolveWithAlphaPS; RenderTarget = ConvolutionBloomFFTTex2; }        //ConvolutionBloomFFTTex -> ConvolutionBloomFFTTex2 
    pass BloomiFFTX         {ComputeShader = FourierPassMainInverseXCS<GROUP_SIZE_X, 1>; DispatchSizeX = 1; DispatchSizeY = FFT_SIZE_Y; } //ConvolutionBloomFFTTex2 -> ConvolutionBloomFFTTex
    pass BloomiFFTY         {ComputeShader = FourierPassMainInverseYCS<1, GROUP_SIZE_Y>; DispatchSizeX = FFT_SIZE_X; DispatchSizeY = 1; } //ConvolutionBloomFFTTex -> ConvolutionBloomFFTTex2
    pass Blend              {VertexShader = MainVS;  PixelShader = BlendPS;  }  
}
