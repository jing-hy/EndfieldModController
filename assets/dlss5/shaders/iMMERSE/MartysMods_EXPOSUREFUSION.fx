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

    Retinex Test

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform float EXPOSURE_TARGET <
	ui_type = "drag";
	ui_min = 0.1; ui_max = 0.9;
	ui_label = "Target Brightness";
    ui_tooltip = "Target average brightness to optimize for.\n"
                 "Higher values produce an overall brighter image.";
> = 0.666;

uniform float INTENSITY <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Intensity";
    ui_tooltip = "Positive values lift dark areas and tone down bright areas,\n"
                 "visually flattening the image. Negative values do the opposite.";
    ui_section = "V2";
> = 0.5;

uniform float EQUALIZATION_STRENGTH <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Equalization Strength";
    ui_tooltip = "Higher values suppress larger features, making the image even flatter.\n"
                 "Extreme values would produce a deep-fried look.";
> = 0.5;

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
texture DepthInputTex : DEPTH;
sampler DepthInput 	{ Texture = DepthInputTex;};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_texture.fxh"
#include ".\MartysMods\mmx_depth.fxh"
#include ".\MartysMods\mmx_math.fxh"

#include ".\MartysMods\mmx_deferred.fxh"

struct VSOUT
{
	float4 vpos : SV_Position;
    float2 uv   : TEXCOORD0;    
};

/*=============================================================================
	Functions
=============================================================================*/

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

#define degamma(_v) ((_v)*0.283799*((2.52405+(_v))*(_v)))
#define regamma(_v) (1.14374*(-0.126893*(_v)+sqrt(_v)))

#define WHITEPOINT 12.0 //don't change, it has a miniscule impact on the image, but low values will cause whites to be dimmed

float3 sdr_to_hdr(float3 c)
{ 
    c = cone_overlap(c);
    c = c * sqrt(1e-6 + dot(c, c)) / 1.733;    
    float a = 1 + exp2(-WHITEPOINT);   
    c = c / (a - c); 
    return c;
}

float3 hdr_to_sdr(float3 c)
{      
    float a = 1 + exp2(-WHITEPOINT); 
    c = a * c * rcp(1 + c);
    c *= 1.733;
    c = c * rsqrt(sqrt(dot(c, c))+0.0001);  
    c = cone_overlap_inv(c);
    c = saturate(c);
    return c;
}

float get_sdr_luma(float3 c)
{
    c = degamma(c);
    float lum = dot(c, float3(0.2125, 0.7154, 0.0721));
    lum = regamma(lum);
    return lum;
}

/*=============================================================================
	Shader Entry Points
=============================================================================*/

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv);
    return o;
}

float2 downsample_kuwahara(const sampler s0, float2 uv, const bool horizontal)
{
    const float2 texelsize = rcp(tex2Dsize(s0, 0));  
    float2 axis = horizontal ? float2(texelsize.x, 0) : float2(0, texelsize.y);

    float4 mL = 0;
    float4 mR = 0;
    float2 wsum = 0;

    [unroll]
    for(int j = -11; j <= 11; j++)
    {
        float2 off = j * axis;
        float2 tuv = uv + off;
        float w = exp(-j*j/121.0 * 3.0) * Math::inside_screen(tuv);
            
        float2 t = tex2Dlod(s0, tuv, 0).xy;

        w *= j == 0 ? 0.5 : 1;
        mL += float4(t, t * t) * w * (j <= 0);
        mR += float4(t, t * t) * w * (j >= 0);
        wsum += w * float2(j <= 0, j >= 0);
    }

    mL /= wsum.x; 
    mR /= wsum.y;
    float vL = max(0, mL.w - mL.y * mL.y); //.y .w is the regular luma BS so we can use that as weight
    float vR = max(0, mR.w - mR.y * mR.y);
    float2 w = rcp(0.25 + sqrt(float2(vL, vR)));
    return (mL.xy * w.x + mR.xy * w.y) / (w.x + w.y);    
}

//this is really awkward but we cannot use any of the common preprocessor integer log2 macros
//as the preprocessor runs out of stack space with them. So we have to do it manually like this

#define RESOLUTION_DIV 2

#define WIDTH   (BUFFER_WIDTH / RESOLUTION_DIV)
#define HEIGHT  (BUFFER_HEIGHT / RESOLUTION_DIV)

#if HEIGHT < 128
    #define LOWEST_LEVEL  3
#elif HEIGHT < 256
    #define LOWEST_LEVEL  4
#elif HEIGHT < 512
    #define LOWEST_LEVEL  5
#elif HEIGHT < 1024
    #define LOWEST_LEVEL  6
#elif HEIGHT < 2048
    #define LOWEST_LEVEL  7
#elif HEIGHT < 4096
    #define LOWEST_LEVEL  8
#elif HEIGHT < 8192
    #define LOWEST_LEVEL  9
#elif HEIGHT < 16384
   #define LOWEST_LEVEL   10
#else 
    #error "Unsupported resolution"
#endif

texture RetinexPyramidL0     { Width = WIDTH>>0; Height = HEIGHT>>0; Format = RG16F;};
sampler sRetinexPyramidL0    { Texture = RetinexPyramidL0;};
#if LOWEST_LEVEL >= 1
texture RetinexPyramidL1Tmp  { Width = WIDTH>>1; Height = HEIGHT>>0; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL1Tmp { Texture = RetinexPyramidL1Tmp;};
texture RetinexPyramidL1     { Width = WIDTH>>1; Height = HEIGHT>>1; Format = RG16F;};
sampler sRetinexPyramidL1    { Texture = RetinexPyramidL1;};
void DownsamplePS0H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL0,    i.uv, true);}
void DownsamplePS0V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL1Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 2
texture RetinexPyramidL2Tmp  { Width = WIDTH>>2; Height = HEIGHT>>1; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL2Tmp { Texture = RetinexPyramidL2Tmp;};
texture RetinexPyramidL2     { Width = WIDTH>>2; Height = HEIGHT>>2; Format = RG16F;};
sampler sRetinexPyramidL2    { Texture = RetinexPyramidL2;};
void DownsamplePS1H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL1,    i.uv, true);}
void DownsamplePS1V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL2Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 3
texture RetinexPyramidL3Tmp  { Width = WIDTH>>3; Height = HEIGHT>>2; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL3Tmp { Texture = RetinexPyramidL3Tmp;};
texture RetinexPyramidL3     { Width = WIDTH>>3; Height = HEIGHT>>3; Format = RG16F;};
sampler sRetinexPyramidL3    { Texture = RetinexPyramidL3;};
void DownsamplePS2H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL2,    i.uv, true);}
void DownsamplePS2V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL3Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 4
texture RetinexPyramidL4Tmp  { Width = WIDTH>>4; Height = HEIGHT>>3; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL4Tmp { Texture = RetinexPyramidL4Tmp;};
texture RetinexPyramidL4     { Width = WIDTH>>4; Height = HEIGHT>>4; Format = RG16F;};
sampler sRetinexPyramidL4    { Texture = RetinexPyramidL4;};
void DownsamplePS3H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL3,    i.uv, true);}
void DownsamplePS3V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL4Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 5
texture RetinexPyramidL5Tmp  { Width = WIDTH>>5; Height = HEIGHT>>4; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL5Tmp { Texture = RetinexPyramidL5Tmp;};
texture RetinexPyramidL5     { Width = WIDTH>>5; Height = HEIGHT>>5; Format = RG16F;};
sampler sRetinexPyramidL5    { Texture = RetinexPyramidL5;};
void DownsamplePS4H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL4,    i.uv, true);}
void DownsamplePS4V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL5Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 6
texture RetinexPyramidL6Tmp  { Width = WIDTH>>6; Height = HEIGHT>>5; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL6Tmp { Texture = RetinexPyramidL6Tmp;};
texture RetinexPyramidL6     { Width = WIDTH>>6; Height = HEIGHT>>6; Format = RG16F;};
sampler sRetinexPyramidL6    { Texture = RetinexPyramidL6;};
void DownsamplePS5H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL5,    i.uv, true);}
void DownsamplePS5V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL6Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 7
texture RetinexPyramidL7Tmp  { Width = WIDTH>>7; Height = HEIGHT>>6; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL7Tmp { Texture = RetinexPyramidL7Tmp;};
texture RetinexPyramidL7     { Width = WIDTH>>7; Height = HEIGHT>>7; Format = RG16F;};
sampler sRetinexPyramidL7    { Texture = RetinexPyramidL7;};
void DownsamplePS6H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL6,    i.uv, true);}
void DownsamplePS6V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL7Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 8
texture RetinexPyramidL8Tmp  { Width = WIDTH>>8; Height = HEIGHT>>7; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL8Tmp { Texture = RetinexPyramidL8Tmp;};
texture RetinexPyramidL8     { Width = WIDTH>>8; Height = HEIGHT>>8; Format = RG16F;};
sampler sRetinexPyramidL8    { Texture = RetinexPyramidL8;};
void DownsamplePS7H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL7,    i.uv, true);}
void DownsamplePS7V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL8Tmp, i.uv, false);}
#endif
#if LOWEST_LEVEL >= 9
texture RetinexPyramidL9Tmp  { Width = WIDTH>>9; Height = HEIGHT>>8; Format = RG16F;}; //for horizontal blur
sampler sRetinexPyramidL9Tmp { Texture = RetinexPyramidL1Tmp;};
texture RetinexPyramidL9     { Width = WIDTH>>9; Height = HEIGHT>>9; Format = RG16F;};
sampler sRetinexPyramidL9    { Texture = RetinexPyramidL9;};
void DownsamplePS8H(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL8,    i.uv, true);}
void DownsamplePS8V(in VSOUT i, out float2 o : SV_Target0){o = downsample_kuwahara(sRetinexPyramidL9Tmp, i.uv, false);}
#endif

texture FusedRetinexPyramid    { Width = WIDTH>>0; Height = HEIGHT>>0; Format = RG16F;};
sampler sFusedRetinexPyramid    { Texture = FusedRetinexPyramid;};

void InitRetinexPyramidPS(in VSOUT i, out float2 o : SV_Target0)
{
    float3 hdr = sdr_to_hdr(tex2D(ColorInput, i.uv).rgb);
    float loglum = dot(0.3333, log2(max(1e-3, hdr)));
    o.y = loglum; //key to .y  
    o.x = -loglum * INTENSITY * 0.5;
}

float func(float a, float b, float levelnorm)
{
    float res = abs(a - b) / max3(a, b, 1);
    res *= lerp(0.02, 0.3, EQUALIZATION_STRENGTH);    
    return saturate(res / (1 + res));
}

void FusePS(in VSOUT i, out float2 o : SV_Target0)
{
    float2 G[LOWEST_LEVEL + 1];
    G[0] = tex2D(sRetinexPyramidL0, i.uv).xy;
#if LOWEST_LEVEL >= 1
    G[1] = tex2D(sRetinexPyramidL1, i.uv).xy;
#endif
#if LOWEST_LEVEL >= 2
    G[2] = tex2D(sRetinexPyramidL2, i.uv).xy;
#endif
#if LOWEST_LEVEL >= 3
    G[3] = tex2D(sRetinexPyramidL3, i.uv).xy;
#endif
#if LOWEST_LEVEL >= 4
    G[4] = Texture::sample2D_bspline(sRetinexPyramidL4, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 4).xy;
#endif
#if LOWEST_LEVEL >= 5
    G[5] = Texture::sample2D_bspline(sRetinexPyramidL5, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 5).xy;
#endif
#if LOWEST_LEVEL >= 6
    G[6] = Texture::sample2D_bspline(sRetinexPyramidL6, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 6).xy;
#endif
#if LOWEST_LEVEL >= 7
    G[7] = Texture::sample2D_bspline(sRetinexPyramidL7, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 7).xy;
#endif
#if LOWEST_LEVEL >= 8
    G[8] = Texture::sample2D_bspline(sRetinexPyramidL8, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 8).xy;
#endif
#if LOWEST_LEVEL >= 9
    G[9] = Texture::sample2D_bspline(sRetinexPyramidL9, i.uv, (BUFFER_SCREEN_SIZE / RESOLUTION_DIV) >> 9).xy;
#endif

    float2 bias = G[LOWEST_LEVEL]; //keep .y to blend

    [unroll]
    for(int j = LOWEST_LEVEL - 1; j >= 0; j--)
    {
        bias = lerp(bias, G[j], func(G[j].y, bias.y, float(j) / LOWEST_LEVEL));
    }

    o.x = bias.x;
    o.y = dot(0.3333, tex2D(ColorInput, i.uv).rgb);
}

void MainPS(in VSOUT i, out float3 o : SV_Target0)
{
    float4 m = 0;
    float ws = 0.0;

    [unroll]for(int y = -1; y <= 1; y++) 
    [unroll]for(int x = -1; x <= 1; x++)    
    {
        float2 t = tex2D(sFusedRetinexPyramid, i.uv, int2(x, y)).xy;
        float w = exp(-(x * x + y * y));
        m += float4(t.y, t.y * t.y, t.y * t.x, t.x) * w;
        ws += w;
    }    

    m /= ws;    
    float a = (m.z - m.x * m.w) / (max(m.y - m.x * m.x, 0.0) + 0.00001);
    float b = m.w - a * m.x;

    float guide = dot(0.3333, tex2D(ColorInput, i.uv).rgb);
    float bias = a * guide + b;

    float3 target_hdr = sdr_to_hdr(EXPOSURE_TARGET.xxx);
    float target_loglum = dot(0.3333, log2(max(1e-3, target_hdr)));  
    bias += target_loglum * abs(INTENSITY); 

    o = tex2D(ColorInput, i.uv).rgb;
    o = sdr_to_hdr(o);    
    o *= exp2(bias);  
    o = hdr_to_sdr(o);
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_EXPOSUREFUSION
<
    ui_label = "iMMERSE Pro: Exposure Fusion";
    ui_tooltip =        
        "                          MartysMods - EXPOSURE FUSION                        \n"
        "                   MartysMods Epic ReShade Effects (iMMERSE)                  \n"
        "______________________________________________________________________________\n"
        "\n"

        "Exposure Fusion improves visibility by selectively adjusting the brightness in\n"
        "different screen areas. Photos are commonly developed using localized tonemap\n" 
        "operators, but most games only contain global tonemappers, which only adjust\n"
        "the brightness for the entire image. This shader retrofits this functionality.\n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                            \n"
        "\n"       
        "______________________________________________________________________________";
>
{
    pass    {VertexShader = MainVS;PixelShader = InitRetinexPyramidPS;  RenderTarget0 = RetinexPyramidL0; }     
#if LOWEST_LEVEL >= 1
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS0H;  RenderTarget0 = RetinexPyramidL1Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS0V;  RenderTarget0 = RetinexPyramidL1; } 
#endif
#if LOWEST_LEVEL >= 2
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS1H;  RenderTarget0 = RetinexPyramidL2Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS1V;  RenderTarget0 = RetinexPyramidL2; }
#endif
#if LOWEST_LEVEL >= 3 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS2H;  RenderTarget0 = RetinexPyramidL3Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS2V;  RenderTarget0 = RetinexPyramidL3; }
#endif
#if LOWEST_LEVEL >= 4 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS3H;  RenderTarget0 = RetinexPyramidL4Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS3V;  RenderTarget0 = RetinexPyramidL4; } 
#endif
#if LOWEST_LEVEL >= 5 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS4H;  RenderTarget0 = RetinexPyramidL5Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS4V;  RenderTarget0 = RetinexPyramidL5; }
#endif
#if LOWEST_LEVEL >= 6 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS5H;  RenderTarget0 = RetinexPyramidL6Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS5V;  RenderTarget0 = RetinexPyramidL6; }
#endif
#if LOWEST_LEVEL >= 7 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS6H;  RenderTarget0 = RetinexPyramidL7Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS6V;  RenderTarget0 = RetinexPyramidL7; }
#endif
#if LOWEST_LEVEL >= 8 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS7H;  RenderTarget0 = RetinexPyramidL8Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS7V;  RenderTarget0 = RetinexPyramidL8; }
#endif 
#if LOWEST_LEVEL >= 9 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS8H;  RenderTarget0 = RetinexPyramidL9Tmp; } 
    pass    {VertexShader = MainVS;PixelShader = DownsamplePS8V;  RenderTarget0 = RetinexPyramidL9; }
#endif
    pass    {VertexShader = MainVS; PixelShader = FusePS; RenderTarget0 = FusedRetinexPyramid; }
    pass    {VertexShader = MainVS; PixelShader = MainPS; }
}