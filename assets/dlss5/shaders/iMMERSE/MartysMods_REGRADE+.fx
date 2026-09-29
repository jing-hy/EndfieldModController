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

    ReGrade+ Companion Shader

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/

/*=============================================================================
	Preprocessor definitions
=============================================================================*/

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
	UI Uniforms
=============================================================================*/

uniform int REGRADE_LUT_MODE < 
    ui_type = "combo";
	ui_items = "Trilinear\0Tetrahedral\0";
	ui_label = "LUT Sampling Mode";
> = 1;

#define SCOPE_MODE_HISTOGRAM_LUMA              0
#define SCOPE_MODE_HISTOGRAM_RGB               1
#define SCOPE_MODE_WAVEFORM_LUMA               2
#define SCOPE_MODE_WAVEFORM_RGB                3
#define SCOPE_MODE_WAVEFORM_RGB_PARADE         4
#define SCOPE_MODE_VECTORSCOPE                 5
#define SCOPE_MODE_VECTORSCOPE_2X              6

uniform int EXT_SCOPE_MODE < hidden = true; >  = SCOPE_MODE_HISTOGRAM_RGB;
uniform uint EXT_CURVES_MODE < hidden = true; > = 3u;

uniform bool EXT_BW_ENABLE < hidden = true; >;

uniform float  E_BYPASS_WHITEBALANCE        < hidden = true; >;
uniform float  E_BYPASS_EXPOSURE            < hidden = true; >;
uniform float  E_BYPASS_HDR                 < hidden = true; >;
uniform float  E_BYPASS_CURVES              < hidden = true; >;
uniform float  E_BYPASS_SPLITTONE           < hidden = true; >;
uniform float  E_BYPASS_COLORISTA           < hidden = true; >;

//basic adjustments params
uniform float  E_EXPOSURE      < hidden = true; >;
uniform float  E_CONTRAST      < hidden = true; >;
uniform float  E_GAMMA         < hidden = true; >;
uniform float  E_FILMICGAMMA   < hidden = true; >;
uniform float  E_SHADOWS       < hidden = true; >;
uniform float  E_DARKS         < hidden = true; >;
uniform float  E_LIGHTS        < hidden = true; >;
uniform float  E_HIGHLIGHTS    < hidden = true; >;
uniform float  E_SATURATION    < hidden = true; >;
uniform float  E_VIBRANCE      < hidden = true; >;
uniform float  E_TEMP          < hidden = true; > = 6500.0; //all others are default 0, can leave it
uniform float  E_TINT          < hidden = true; >;

uniform float  E_SHADOWS_HUE         < hidden = true; >;
uniform float  E_SHADOWS_SAT         < hidden = true; >;
uniform float  E_MIDTONES_HUE        < hidden = true; >;
uniform float  E_MIDTONES_SAT        < hidden = true; >;
uniform float  E_HIGHLIGHTS_HUE      < hidden = true; >;
uniform float  E_HIGHLIGHTS_SAT      < hidden = true; >;

uniform float3  E_COLORISTA_HSL_RED_V2      < hidden = true; > = float3(0, 0, 0);
uniform float3  E_COLORISTA_HSL_ORANGE_V2   < hidden = true; > = float3(1.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_YELLOW_V2   < hidden = true; > = float3(2.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_GREEN_V2    < hidden = true; > = float3(4.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_CYAN_V2     < hidden = true; > = float3(6.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_BLUE_V2     < hidden = true; > = float3(8.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_PURPLE_V2   < hidden = true; > = float3(9.0/12.0, 0, 0);
uniform float3  E_COLORISTA_HSL_MAGENTA_V2  < hidden = true; > = float3(10.0/12.0, 0, 0);

//these are only for the curves regeneration - the addon needs to read the node coords, convert that into a system of equation, solve _that_ with Sparse LU and then update the LUT

//I store the coords quantized to 8 bit each, so 16 bit uints, to reduce constant register usage on DX9 (the jackass)
uniform uint EXT_CURVES_NODE_COUNT_RGB    < hidden = true; >; //keep default at invalid value (0) so we can save the init
uniform uint EXT_CURVES_NODE_COORDS_RGB0  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB1  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB2  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB3  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB4  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB5  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB6  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB7  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB8  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_RGB9  < hidden = true; >;

uniform uint  EXT_CURVES_NODE_COUNT_R     < hidden = true; >; //keep default at invalid value (0) so we can save the init
uniform uint EXT_CURVES_NODE_COORDS_R0    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R1    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R2    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R3    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R4    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R5    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R6    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R7    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R8    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_R9    < hidden = true; >;

uniform uint  EXT_CURVES_NODE_COUNT_G     < hidden = true; >; //keep default at invalid value (0) so we can save the init
uniform uint EXT_CURVES_NODE_COORDS_G0    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G1    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G2    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G3    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G4    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G5    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G6    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G7    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G8    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_G9    < hidden = true; >;

uniform uint  EXT_CURVES_NODE_COUNT_B     < hidden = true; >; //keep default at invalid value (0) so we can save the init
uniform uint EXT_CURVES_NODE_COORDS_B0    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B1    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B2    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B3    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B4    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B5    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B6    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B7    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B8    < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_B9    < hidden = true; >;

//black and white params
uniform float  E_BW_PRE_HUE      < hidden = true; >;
uniform float  E_BW_PRE_SAT      < hidden = true; >;
/*
uniform uint EXT_CURVES_NODE_COUNT_BWHUE    < hidden = true; >; //keep default at invalid value (0) so we can save the init
uniform uint EXT_CURVES_NODE_COORDS_BWHUE0  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE1  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE2  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE3  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE4  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE5  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE6  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE7  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE8  < hidden = true; >;
uniform uint EXT_CURVES_NODE_COORDS_BWHUE9  < hidden = true; >;
*/
/*=============================================================================
	Textures, Samplers, Globals, Structs
=============================================================================*/

//do NOT change anything here. "hurr durr I changed this and now it works"
//you ARE breaking things down the line, if the shader does not work without changes
//here, it's by design.

texture ColorInputTex : COLOR;
sampler ColorInput 	{ Texture = ColorInputTex; MinFilter=POINT; MipFilter=POINT;MagFilter=POINT;};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_math.fxh"
#include ".\MartysMods\mmx_qmc.fxh"
#include ".\MartysMods\mmx_colorspaces.fxh"
#include ".\MartysMods\mmx_texture.fxh"


uniform uint FRAMECOUNT  < source = "framecount"; >;

 
//An analysis covering all possible colors yielded these magic numbers
//as viable minima for single channel and compounded error to neutral LUT
//Results vary a bit for analysis using colors weighted by natural occurence
//and average weighting entire RGB cube. 
//Values were picked that score well in both and R*B < 4096 (DX9 limit)
#define LUT_DIM_R    51 
#define LUT_DIM_G    84
#define LUT_DIM_B    34

#define LUT_DIM_X (LUT_DIM_R * LUT_DIM_B)
#define LUT_DIM_Y (LUT_DIM_G)

//stuff until curves
texture2D ReGradePlusLUTTexA	{ Width = LUT_DIM_X;   Height = LUT_DIM_Y; Format = RGBA32F; };
sampler2D sReGradePlusLUTTexA	{ Texture = ReGradePlusLUTTexA; };
//Curves are 1D operations on each channel separately and might have sharp turns, so 3D data is not suitable
texture2D ReGradePlusCurvesLUTTex	{ Width = 256; Height = 1; Format = RGBA8; };
sampler2D sReGradePlusCurvesLUTTex	{ Texture = ReGradePlusCurvesLUTTex; };
//stuff after curves
texture2D ReGradePlusLUTTexB	{ Width = LUT_DIM_X;   Height = LUT_DIM_Y; Format = RGBA32F; };
sampler2D sReGradePlusLUTTexB	{ Texture = ReGradePlusLUTTexB; };

//histogram CPU/GPU interop texture
texture2D API_TEX_HISTOGRAM_TITLE	{ Width = 256; Height = 1; Format = RGBA32F; };
//waveform CPU/GPU interop texture
texture2D API_TEX_SCOPE_TITLE       { Width = 1024; Height = 512; Format = RGBA8; };

texture2D ReGradePlusBackbufferClone	{ Width = BUFFER_WIDTH;   Height = BUFFER_HEIGHT; Format = RGBA8; };
sampler2D sReGradePlusBackbufferClone	{ Texture = ReGradePlusBackbufferClone; };


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

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    return o;
}

//todo move to includez
float3 xyY_to_xyz(float3 xyY)
{
    return float3(xyY.x * xyY.z / xyY.y, xyY.z, (1.0 - xyY.x - xyY.y) * xyY.z / xyY.y);
}

float3 rgb_to_ypbpr(float3 rgb)
{
    float Y = dot(rgb, float3(0.2126, 0.7152, 0.0722));
    float Pb = (0.5 / (1 - 0.0722)) * (rgb.b - Y);
    float Pr = (0.5 / (1 - 0.2126)) * (rgb.r - Y);
    return float3(Y, Pb, Pr);
}

float3 ypbpr_to_rgb(float3 ypbpr)
{
    float Y = ypbpr.x;
    float Pb = ypbpr.y;
    float Pr = ypbpr.z;
    float b = (Pb / (0.5 / (1 - 0.0722))) + Y;
    float r = (Pr / (0.5 / (1 - 0.2126))) + Y;
    float g = (Y - 0.2126 * r - 0.0722 * b) / 0.7152;
    return float3(r, g, b);
}

float harderstep(float x, float a)
{
    float b = 1 - 2 * x;
    return (sign(b) * (pow(abs(b), a)) + 2 * a * x - 1) / (2 * a - 2);
}

float p(float x)  
{ 
    return x < 0.3333333 ? x * (-3.0 * x * x + 1.0) 
                         : 1.5 * x * (1.0 + x * (x - 2.0)); 
}

float shadows(float x)
{
    return p(saturate(x * 2.0)) * 0.5;
}

float darks(float x)
{
    return p(x);    
}

float lights(float x)
{
    return p(1.0 - x);
}

float highlights(float x)
{
    return lights(saturate(x * 2.0 - 1.0)) * 0.5;
}

float tonecurve(float x, float int_s, float int_d, float int_l, float int_h)
{    
    float s = x;
    x += shadows(s) * int_s;
    x += darks(x) * int_d;
    x += lights(s) * int_l;
    x += highlights(x) * int_h;
	return x;
}

float3 adjustments(float3 col, float exposure, float contrast, float gamma, float vibrance, float saturation, float filmic_gamma, float int_s, float int_d, float int_l, float int_h)
{
    if(!E_BYPASS_EXPOSURE)
    {
        col = Colorspace::srgb_to_linear(col);
        col *= exp2(exposure); //exposure in linear space - this makes no _visual_ difference but alters the response of the exposure curve
        col = Colorspace::linear_to_srgb(col);
        col = saturate(col);

        float3 tcol = col * filmic_gamma * (filmic_gamma > 0 ? 6.0 : 0.6);
        col = (tcol + col) / (tcol + 1);
        col = saturate(col);

        col = pow(col, exp2(-gamma));
        float3 contrasted = col - 0.5;
        contrasted = (contrasted / (0.5 + abs(contrasted))) + 0.5; //CJ.dk
        col = lerp(col, contrasted, contrast);
    }
    if(!E_BYPASS_HDR)
    {    
        col = saturate(col);
        col.r = tonecurve(col.r, int_s, int_d, int_l, int_h);
        col.g = tonecurve(col.g, int_s, int_d, int_l, int_h);
        col.b = tonecurve(col.b, int_s, int_d, int_l, int_h);
        col = saturate(col);
    } 
    if(!E_BYPASS_EXPOSURE)
    {
        float luma = Colorspace::linear_to_srgb(dot(Colorspace::srgb_to_linear(col), float3(0.2126729, 0.7151522, 0.0721750))).x;
        float3 v_sat = col - luma;

        float3 k = v_sat < 0.0.xxx ? col : 1 - col;
        k /= abs(v_sat) + 1e-6;
        float min_k = min(min(k.x, k.y), k.z); //which component saturates earliest?

        float vib = vibrance;
        vib *= vib > 0 ? min_k * rsqrt(vib * vib + min_k * min_k) : saturate(1 - rcp(1 + min_k));

        float final_sat = vib * (1 + saturation) + saturation;
        final_sat = clamp(final_sat, -1, min_k); //force limit to prevent hueshifts

        //old v1
        //col += v_sat * final_sat;
        //v2 density-like
        float m0 = maxc(col);
        col += v_sat * final_sat;
        float m1 = maxc(col);
        col *= m0 / max(1e-6, m1);
    }
    return col;
}

float3 soft_light(float3 base, float3 blend)
{	
	return pow(base, exp2(1 - 2 * blend));
}

float3 color_balance(float3 c, float2 bal_sh, float2 bal_mid, float2 bal_hi)
{
    //better use some perceptually well fitting estimate
    float luma = Colorspace::linear_to_srgb(dot(Colorspace::srgb_to_linear(c), float3(0.2126729, 0.7151522, 0.0721750))).x;

    float3 offsetSMH = float3(0, 0.5, 1);
    float3 widthSMH = float3(2.0, 1.0, 2.0);

    float3 weightSMH = saturate(1 - 2 * abs(luma - offsetSMH) / widthSMH);
    weightSMH = weightSMH * weightSMH * (3 - 2 * weightSMH);
    weightSMH *= weightSMH; //these do not sum up to 1.0, makes no sense in Lightroom either
    weightSMH.z *= 2.0;

    float3 tintcolorS = Colorspace::hsl_to_rgb(float3(frac(0.5 + bal_sh.x), 1, 0.5));
    float3 tintcolorM = Colorspace::hsl_to_rgb(float3(frac(0.5 + bal_mid.x), 1, 0.5));
    float3 tintcolorH = Colorspace::hsl_to_rgb(float3(frac(0.5 + bal_hi.x), 1, 0.5));

    return length(c) * normalize(pow(abs(c), exp2(tintcolorS * weightSMH.x * bal_sh.y*bal_sh.y
                                           + tintcolorM * weightSMH.y * bal_mid.y*bal_mid.y
                                           + tintcolorH * weightSMH.z * bal_hi.y*bal_hi.y)));
}

float2 blackbody_xy(float T)
{
    float term = 1000.0 / T;

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

    float4 xc;
    xc.w = 1.0;
    xc.xyz = term;
    xc.xy *= term;
    xc.x *= term;

    float x = dot(xc, T > 4000.0 ? xc_coefficients[0] : xc_coefficients[1]); //xc

    float4 yc;
    yc.w = 1.0;
    yc.xyz = x;
    yc.xy *= x;
    yc.x *= x;

    float y = dot(yc, T < 2222.0 ? yc_coefficients[0] : (T < 4000.0 ? yc_coefficients[1] : yc_coefficients[2])); //yc

    return float2(x, y);
}

float3x3 chromatic_adaptation(float3 xyz_src, float3 xyz_dst)
{
    //bradford CIECAM97   
    const float3x3 m_bfd  = float3x3(0.8951, 0.2664, -0.1614,
                                    -0.7502, 1.7135, 0.0367,
                                     0.0389, -0.0685, 1.0296);
    const float3x3 m_bdf_i = float3x3(0.9869929, -0.1470543, 0.1599627,
                                      0.4323053, 0.5183603, 0.0492912,
                                      -0.0085287, 0.0400428, 0.9684867);                             

    float3 lms_src = mul(xyz_src, m_bfd);
    float3 lms_dst = mul(xyz_dst, m_bfd);

    float3x3 von_kries_m = float3x3(lms_dst.x / lms_src.x, 0, 0,
                                    0, lms_dst.y / lms_src.y, 0,
                                    0, 0, lms_dst.z / lms_src.z);

    return mul(mul(m_bfd, von_kries_m), m_bdf_i);
}

float3 whitebalance(float3 rgb, float T, float tint)
{
    float2 xy_src = blackbody_xy(6500.0);
    float2 xy_dst = blackbody_xy(T);

    float2 tangent = blackbody_xy(T + 1.0) - xy_dst;
    float2 isotherm = normalize(float2(tangent.y, -tangent.x));

    xy_dst += isotherm * tint / 30.0; //Lightroom displays DUV * 3000, but they use +-100 as opposed to +-1.0

    float3 xyz_src = xyY_to_xyz(float3(xy_src, 1.0));
    float3 xyz_dst = xyY_to_xyz(float3(xy_dst, 1.0));

    float3 adjusted = Colorspace::rgb_to_xyz(rgb);
    adjusted = mul(adjusted, chromatic_adaptation(xyz_src, xyz_dst));
    adjusted = Colorspace::xyz_to_rgb(adjusted);
    return saturate(adjusted);
}

float3 color_remapper(in float3 rgb, float3 modifier_red, 
    	                             float3 modifier_orange, 
                                     float3 modifier_yellow, 
                                     float3 modifier_green, 
                                     float3 modifier_aqua, 
                                     float3 modifier_blue, 
                                     float3 modifier_purple,
                                     float3 modifier_magenta)
{
    static const float hue_nodes[9] = {	 0.0, 1.0/12.0, 2.0/12.0, 4.0/12.0, 6.0/12.0, 8.0/12.0, 9.0/12.0, 10.0/12.0, 1.0};
    float hue = Colorspace::rgb_to_hsl(rgb).x;
    
    float risingedges[8];
    for(int j = 0; j < 8; j++) risingedges[j] = linearstep(hue_nodes[j], hue_nodes[j + 1], hue);

    float hueweights[8];    
    hueweights[0] = ((1.0 - risingedges[0]) + risingedges[7]); //this goes over the 2 pi boundary, so this needs special treatment
    for(int j = 1; j < 8; j++) hueweights[j] = ((1.0 - risingedges[j]) * risingedges[j - 1]); 

    float3 hue_modifiers[8] = {modifier_red, modifier_orange, modifier_yellow, modifier_green, modifier_aqua, modifier_blue, modifier_purple, modifier_magenta};
    float3 LChmod = 0;

    float3 oklab = Colorspace::rgb_to_oklab(rgb);
    float3 ret = 0;

    [loop]
    for(int hue = 0; hue < 8; hue++)
    {
        float w = hueweights[hue];
        w = w * w * (3.0 - 2.0 * w); //smoothstep - integral is energy conserving vs linear, otherwise we'd need to normalize weights here!!
        
        LChmod.z = hue_modifiers[hue].x - hue_nodes[hue];
        LChmod.z *= 2;
        LChmod.xy = hue_modifiers[hue].zy;

        float3 adjusted_oklab = oklab;

        //adjusted_oklab.x *= exp2(LChmod.x * 0.33333); //legacy - visual parity to HSL based tools
        adjusted_oklab.x = pow(max(0, adjusted_oklab.x), exp2(-LChmod.x * 4 * length(adjusted_oklab.yz))); //better, leaves greys untouched. Not sure if sqrt is needed
        float2 huesc; sincos(-3.14159265 * LChmod.z, huesc.x, huesc.y); 
        adjusted_oklab.yz = mul(adjusted_oklab.yz, float2x2(huesc.y, -huesc.x, huesc.x, huesc.y)); 

         adjusted_oklab.yz = LChmod.y < 0 
             ? adjusted_oklab.yz * (1 + LChmod.y) //reduce saturation -> saturation 0%-100%
             : safenormalize(adjusted_oklab.yz) * pow(length(adjusted_oklab.yz) * 2.0, exp2(-LChmod.y * 0.5)) * 0.5; //increase saturation -> vibrance

        ret += adjusted_oklab * w;
    }

    ret = Colorspace::oklab_to_rgb(ret);
    ret = saturate(ret);
    return ret;
}

float3 draw_lut(float2 coord, int3 volumesize) //need float2 due to DX9 being a jackass
{
    coord.y %= volumesize.y;
    float3 col = float3(coord.x % volumesize.x, coord.y, floor(coord.x / volumesize.x));
    return saturate(col / (volumesize - 1.0));
}

/*=============================================================================
	Shader Entry Points - Color Mode
=============================================================================*/

VSOUT ColorModeVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    if(EXT_BW_ENABLE) 
    {
        o.vpos = 0;
    }
    return o;
}

void ColorModeLUTGenAPS(in VSOUT i, out float3 o : SV_Target0)
{
    o = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    if(!E_BYPASS_WHITEBALANCE) o = whitebalance(o, E_TEMP, E_TINT);
    o = adjustments(o, E_EXPOSURE, E_CONTRAST, E_GAMMA, E_VIBRANCE, E_SATURATION, E_FILMICGAMMA, E_SHADOWS, E_DARKS, E_LIGHTS, E_HIGHLIGHTS);
    o = saturate(o); 
}

void ColorModeLUTGenBPS(in VSOUT i, out float3 o : SV_Target0)
{
    o = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    if(!E_BYPASS_SPLITTONE) o = color_balance(o, float2(E_SHADOWS_HUE, E_SHADOWS_SAT), float2(E_MIDTONES_HUE, E_MIDTONES_SAT), float2(E_HIGHLIGHTS_HUE, E_HIGHLIGHTS_SAT));
    if(!E_BYPASS_COLORISTA) o = color_remapper(o, E_COLORISTA_HSL_RED_V2, E_COLORISTA_HSL_ORANGE_V2, E_COLORISTA_HSL_YELLOW_V2, E_COLORISTA_HSL_GREEN_V2, E_COLORISTA_HSL_CYAN_V2, E_COLORISTA_HSL_BLUE_V2, E_COLORISTA_HSL_PURPLE_V2, E_COLORISTA_HSL_MAGENTA_V2);
}

void ColorModeApplyPS(in VSOUT i, out float3 o : SV_Target0)
{ 
    o = tex2D(ColorInput, i.uv).rgb;

    [branch]
    if(REGRADE_LUT_MODE == 1)
        o = Texture::sample3D_tetrahedral(sReGradePlusLUTTexA, o, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;   
    else
        o = Texture::sample3D_trilinear(sReGradePlusLUTTexA, o, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;

    if(!E_BYPASS_CURVES)
    {    
        o.r = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.r), 0.5), 0).r;
        o.g = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.g), 0.5), 0).g;
        o.b = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.b), 0.5), 0).b;
    }

    [branch]
    if(REGRADE_LUT_MODE == 1)
        o = Texture::sample3D_tetrahedral(sReGradePlusLUTTexB, o, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;   
    else
        o = Texture::sample3D_trilinear(sReGradePlusLUTTexB, o, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;    
}

/*=============================================================================
	Shader Entry Points - Monochrome Mode
=============================================================================*/

VSOUT BWModeVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 
    if(!EXT_BW_ENABLE) 
    {
        o.vpos = 0;
    }
    return o;
}

void BWModeLUTGenAPS(in VSOUT i, out float3 o : SV_Target0)
{
    o = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    //like RGB, except no vibrance and saturation
    o = adjustments(o, E_EXPOSURE, E_CONTRAST, E_GAMMA, 0.0, 0.0, E_FILMICGAMMA, E_SHADOWS, E_DARKS, E_LIGHTS, E_HIGHLIGHTS);
    o = saturate(o); 

/*
    float hue = Colorspace::rgb_to_hsl(o).x;
    float3 oklab = Colorspace::rgb_to_oklab(o);
    float exposure = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, hue), 0.5), 0).g;
    exposure = exposure - 0.5;
    exposure *= 32.0;
    exposure = exp2(exposure * length(oklab.yz));

    o /= 1.01 - o;
    o *= exposure;
    o = 1.01 * o / (1.0 + o); 

    o = Colorspace::rgb_to_oklab(o);
    o.yz = 0;
    o = Colorspace::oklab_to_rgb(o);
*/

/*
    float weighted_exposure = 0;
    float similarity_sum = 0;

    float3 weighted_color = 0;


    [loop]
    for(int j = 0; j < 256; ++j)
    {
        float hue = float(j) / 255.0;
        float3 principal_color = Colorspace::hsv_to_rgb(float3(hue, 1.0, 1.0));
        float curr_exposure = tex2Dfetch(sReGradePlusCurvesLUTTex, int2(j, 0)).y;

        float similarity = dot(principal_color, o);       
        similarity = pow(similarity, 10.0);

        curr_exposure = (curr_exposure - 0.5) * 10;
        curr_exposure = exp2(curr_exposure);

        weighted_color += principal_color * curr_exposure * similarity;

    }

    o = weighted_color / 256.0;

    */

    float3 tintcol = Colorspace::hsv_to_rgb(float3(E_BW_PRE_HUE, E_BW_PRE_SAT * 0.8f, 1.0));
    //tintcol /= dot(tintcol, 0.3333);

    tintcol /= Colorspace::rgb_to_oklab(tintcol).x;
    o /= 1.001 - o;
    o *= tintcol;
    o = 1.001 * o / (1.0 + o);
}

void BWModeCloneBackbufferPS(in VSOUT i, out float4 o : SV_Target0)
{
    o.rgb = tex2D(ColorInput, i.uv).rgb;

    o.rgb = Texture::sample3D_tetrahedral(sReGradePlusLUTTexA, o.rgb, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;   
    o.w = 1;
}

void BWModeApplyPS(in VSOUT i, out float3 o : SV_Target0)
{ 
    o = tex2D(ColorInput, i.uv).rgb;
    //apply LUT prior to curves
    o = Texture::sample3D_tetrahedral(sReGradePlusLUTTexA, o, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;

    o = Colorspace::oklab_to_rgb(Colorspace::rgb_to_oklab(o) * float3(1, 0, 0));
 
    if(!E_BYPASS_CURVES)
    {    
        //in B&W mode, the curve is embedded in the red channel of the LUT texture
        //I could reduce this here to a single channel but for future proofing, e.g. a sepia overlay, I treat RGB individually.
        o.r = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.r), 0.5), 0).r;
        o.g = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.g), 0.5), 0).r;
        o.b = tex2Dlod(sReGradePlusCurvesLUTTex, float2(lerp(0.5/256.0, 255.5 / 256.0, o.b), 0.5), 0).r;
    }    
}

/*=============================================================================
	Histogram Generation
=============================================================================*/

//compute parameters
#define GRP_SIZE_X                  1
#define GRP_SIZE_Y                  1024
#define NUM_PIXELS_X                4
#define WARP_SIZE                   32
#define NUM_HISTOGRAMS              (GRP_SIZE_Y / WARP_SIZE)

#if BUFFER_WIDTH <= 4096
 #define NUM_COLUMNS_X              CEIL_DIV(BUFFER_WIDTH, NUM_PIXELS_X) 
#else 
 #define NUM_COLUMNS_X              CEIL_DIV(4096, NUM_PIXELS_X)
#endif

texture2D ReGradePlusHistogramTex			{ Width = 256; Height = 1; Format = RGBA32F; };
sampler2D sReGradePlusHistogramTex			{ Texture = ReGradePlusHistogramTex; };
storage   stReGradePlusHistogramTex         { Texture = ReGradePlusHistogramTex; };

texture ReGradePlusWaveformTex             { Width = NUM_COLUMNS_X; Height = 256; Format = RGBA32F; };
sampler sReGradePlusWaveformTex            { Texture = ReGradePlusWaveformTex;};
storage stReGradePlusWaveformTex           { Texture = ReGradePlusWaveformTex; };

#if _COMPUTE_SUPPORTED //branch here, we reuse the params above for the DX9 slow path

groupshared uint histo_bins[NUM_HISTOGRAMS * 256];

void WaveformCS(in CSIN i)
{    
    [loop]for(uint x = i.threadid; x < NUM_HISTOGRAMS * 256; x += GRP_SIZE_Y) 
        histo_bins[x] = 0;
    barrier();

    uint warp_id = i.threadid / WARP_SIZE;
    const uint num_sweeps = BUFFER_HEIGHT > GRP_SIZE_Y ? 2 : 1;
    float2 stride = max(1.0, float2(BUFFER_SCREEN_SIZE) / float2(4096, 2048)); //e.g. if we have 4096 height, we need to skip one pixel for a stride of 2
    
    [loop]for(uint sweep = 0; sweep < num_sweeps; sweep++)
    {
        int2 p = uint2(i.groupid.x * NUM_PIXELS_X * stride.x, (i.threadid + GRP_SIZE_Y * sweep) * stride.y);

        if(p.y < BUFFER_HEIGHT) 
        {            
            [loop]for(int x = 0; x < NUM_PIXELS_X; x++)
            {
                if(p.x >= BUFFER_WIDTH) break;

                float4 v = tex2Dfetch(ColorInput, p, 0);
                v.w = dot(v.rgb, float3(0.299, 0.587, 0.114));

                uint4 bin = uint4(v * 255 + 0.5) & 0xFF;         

                atomicAdd(histo_bins[bin.x + warp_id * 256], 1u);
                atomicAdd(histo_bins[bin.y + warp_id * 256], 1u << 8u);
                atomicAdd(histo_bins[bin.z + warp_id * 256], 1u << 16u);
                atomicAdd(histo_bins[bin.w + warp_id * 256], 1u << 24u);
                p.x++;
            }
        }
    }

    barrier();    
    if(i.threadid > 255) return;
      
    uint4 sum = 0;
    for(uint x = 0; x < NUM_HISTOGRAMS; x++)
        sum += (histo_bins[i.threadid + x * 256].xxxx >> uint4(0, 8, 16, 24)) & 0xFF;

    tex2Dstore(stReGradePlusWaveformTex, uint2(i.groupid.x, i.threadid), float4(sum) / (NUM_HISTOGRAMS * NUM_PIXELS_X * min(BUFFER_HEIGHT, 2048)));
}

groupshared float4 binsum[256];

void WaveformToHistogramCS(in CSIN i)
{   
    uint num_columns = tex2Dsize(sReGradePlusWaveformTex).x;

    float4 bin = 0;
    for(uint c = i.threadid; c < num_columns; c += 256u)
        bin += tex2Dfetch(sReGradePlusWaveformTex, uint2(c, i.groupid.x), 0);

    binsum[i.threadid] = bin;
    barrier();

    [unroll]
    for(uint stride = 256 / 4; stride > 0; stride >>= 2)
    {
        if(i.threadid < stride)
            binsum[i.threadid] += binsum[i.threadid + stride] + binsum[i.threadid + stride * 2] + binsum[i.threadid + stride * 3];
        barrier();
    }

    if(i.threadid == 0)
        tex2Dstore(stReGradePlusHistogramTex, uint2(i.dispatchthreadid.x, 0), binsum[0] / num_columns * 16.0);  
}

#else //_COMPUTE_SUPPORTED

#define NUM_SAMPLES_Y           (BUFFER_HEIGHT / 3)
#define NUM_SAMPLES_X           NUM_COLUMNS_X       //writes single histogram for current frame, spread across multiple texture rows
#define PRIMARY_REDUCE_FACTOR   32                  //reducing the entire textur is too slow, so we do it in two steps. First, by 32, then the rest whatever remains

texture ReGradePlusWaveformReduceTexIntermediate             { Width = NUM_COLUMNS_X / PRIMARY_REDUCE_FACTOR; Height = 256; Format = RGBA32F; };
sampler sReGradePlusWaveformReduceTexIntermediate            { Texture = ReGradePlusWaveformReduceTexIntermediate;};

VSOUT WaveformVS(in uint vertex_id : SV_VertexID)
{
    uint channel = vertex_id % 4u;       
    vertex_id /= 4u;                    

    uint2 grid_pos;
    grid_pos.x = vertex_id % NUM_SAMPLES_X;
    grid_pos.y = vertex_id / NUM_SAMPLES_X;

    float2 sample_uv = (grid_pos + 0.5) / float2(NUM_SAMPLES_X, NUM_SAMPLES_Y);
    
    float4 c = tex2Dlod(ColorInput, sample_uv, 0);
    c.w = dot(c.rgb, float3(0.299, 0.587, 0.114));

    VSOUT o;  
    o.vpos.y = (round(dot(c, uint4(0, 1, 2, 3) == channel.xxxx) * 255) + 0.5) / 256.0;
    o.vpos.x = (0.5 + grid_pos.x) / NUM_SAMPLES_X; 
    o.vpos.xy = o.vpos.xy * float2(2, -2) + float2(-1, 1);
    o.vpos.zw = float2(0, 1);
    
    o.uv = channel / 4.0;
    return o;
}

void WaveformPS(in VSOUT i, out float4 o : SV_Target0)
{
	o = float4(int4(0, 1, 2, 3) == int4(round(i.uv.xxxx * 4.0))) * rcp(NUM_SAMPLES_X * NUM_SAMPLES_Y) * 16.0;
}

void WaveformFlattenIntermediatePS(in VSOUT i, out float4 o : SV_Target0)
{
    o = 0;
    [loop]for(float j = 0; j < PRIMARY_REDUCE_FACTOR; j++)
        o += tex2Dfetch(sReGradePlusWaveformTex, int2(i.vpos.x * PRIMARY_REDUCE_FACTOR + j, i.vpos.y));
	o /= PRIMARY_REDUCE_FACTOR;
}

void WaveformFlattenFinalPS(in VSOUT i, out float4 o : SV_Target0)
{
    o = 0;
    
    uint num_rows = tex2Dsize(sReGradePlusWaveformReduceTexIntermediate).x;  
    //ceil division
    uint passes = (num_rows - 1) / 256 + 1; //we do 2 texels at once, hence /128 /2
    
    [loop]for(int j = 0; j < passes; j++)
    [loop]for(int k = 0; k < 128; k++)
    {
    	uint flat_idx = j * 128 + k;
    	float uvx = (flat_idx * 2.0 + 0.5) / num_rows;
    	if(uvx > 1.0) break;    	
    	o += tex2Dlod(sReGradePlusWaveformReduceTexIntermediate, float2(uvx, i.uv.x), 0);    
    }

    o /= num_rows;
    o *= 56.0;  
}
#endif //_COMPUTE_SUPPORTED

/*=============================================================================
	Convert raw scope buffers to data consumed by the addon
=============================================================================*/

//this runs always, to ensure we have a histogram for the curves tool
void TitleHistogramPS(in VSOUT i, out float4 o : SV_Target0)
{
    o = 0;
    float wsum = 0;

    [unroll]
	for(int x = -4; x <= 4; x++)
    {
        float g = exp(-x*x*0.08);
        o += tex2Dfetch(sReGradePlusHistogramTex, int2(i.vpos.x + x, 0)) * g;
        wsum += g;
    }
    o /= wsum;   
}

//this runs only when we display the waveform
void TitleWaveformPS(in VSOUT i, out float4 o : SV_Target0)
{   
    if(EXT_SCOPE_MODE != SCOPE_MODE_WAVEFORM_LUMA && 
       EXT_SCOPE_MODE != SCOPE_MODE_WAVEFORM_RGB &&
       EXT_SCOPE_MODE != SCOPE_MODE_WAVEFORM_RGB_PARADE)
        discard;

    i.uv.y = 1 - i.uv.y;
    float2 pixelsize = float2(1.0/1024, 1.0/512); 
    float3 scope = 0;    

    switch(EXT_SCOPE_MODE)
    {       
        case SCOPE_MODE_WAVEFORM_LUMA: //luma wavefront
        scope = tex2Dlod(sReGradePlusWaveformTex, i.uv, 0).w;
        break;
        case SCOPE_MODE_WAVEFORM_RGB: //rgb wavefront
        scope = tex2Dlod(sReGradePlusWaveformTex, i.uv, 0).rgb;
        break;
        case SCOPE_MODE_WAVEFORM_RGB_PARADE: //rgb wavefront parade
        scope = tex2Dlod(sReGradePlusWaveformTex, float2(frac(i.uv.x * 2.999), i.uv.y), 0).rgb;
        scope *= saturate(uint3(i.uv.xxx * 2.999) == uint3(0,1,2));
        break;
    }    

    o = 0;

    float barsize = 1.04 * pixelsize.y;
    i.uv.y += barsize * 0.5;

    float2 grid = step(frac(i.uv.yy * float2(4.0, 12.0)) / float2(4.0, 12.0), barsize);
    grid   *= step(abs(i.uv.y - 0.5), 0.5 - barsize * 2.0);
    grid.y *= step(0.4, abs(i.uv.y - 0.5));  
    
    o.rgb = saturate(scope * 1000.0);
    o.rgb = lerp(o.rgb, dot(0.333, frac(o.rgb + 0.5)), saturate(grid.x + grid.y));
    
    o.w = 1;
}


texture VectorscopeTex             { Width = 2048; Height = 2048; Format = R32F; };
sampler sVectorscopeTex            { Texture = VectorscopeTex;};

#define VECTORSCOPE_SAMPLES_X (BUFFER_WIDTH  >> 2)
#define VECTORSCOPE_SAMPLES_Y (BUFFER_HEIGHT >> 2)

#if VECTORSCOPE_SAMPLES_X > 2048
    #undef VECTORSCOPE_SAMPLES_X
    #define VECTORSCOPE_SAMPLES_X 2048
#endif 
#if VECTORSCOPE_SAMPLES_Y > 1024
    #undef VECTORSCOPE_SAMPLES_Y
    #define VECTORSCOPE_SAMPLES_Y 1024
#endif

//Clears one of the subsampling sectors
void VectorscopeClearBlockPS(in VSOUT i, out float4 o : SV_Target0)
{ 
    int2 multibin_offset = int2(FRAMECOUNT % 4, (FRAMECOUNT / 4) % 4);   

    float4 aabb;
    aabb.xy = float2(multibin_offset) / 4.0;
    aabb.zw = aabb.xy + 1.0 / 4.0;

    if(all(i.uv.xy >= aabb.xy) && all(i.uv.xy < aabb.zw))
        o = 0;
    else
        discard;
}

float4 VectorscopeScatterVS(in uint id : SV_VertexID) : SV_Position
{
    if(EXT_SCOPE_MODE != SCOPE_MODE_VECTORSCOPE && EXT_SCOPE_MODE != SCOPE_MODE_VECTORSCOPE_2X)
        return -1;

    int2 multibin_offset = int2(FRAMECOUNT % 4, (FRAMECOUNT / 4) % 4);
    multibin_offset.y = 3 - multibin_offset.y; //for the correct sector to write to

    int2 gridpos = int2(id % VECTORSCOPE_SAMPLES_X, id / VECTORSCOPE_SAMPLES_X);
    if(gridpos.y % 2 == 0)
        gridpos.x = VECTORSCOPE_SAMPLES_X - gridpos.x - 1;

    gridpos = gridpos * 4 + multibin_offset; //jitter sample positions per frame 

    float2 uv = float2(gridpos + 0.5) / (4 * float2(VECTORSCOPE_SAMPLES_X, VECTORSCOPE_SAMPLES_Y)); 
    
    float3 ypbpr = rgb_to_ypbpr(tex2Dlod(ColorInput, frac(uv), 0).rgb + (QMC::roberts3(id % 1024, 0.5) - 0.5) / 256.0 * 2.5); 
    ypbpr.yz = EXT_SCOPE_MODE == SCOPE_MODE_VECTORSCOPE_2X ? ypbpr.yz * 2.0 : ypbpr.yz;

    int2 bin = int2((ypbpr.yz + 0.5) * 512.0);  
    bin += multibin_offset * 512;

    float2 texel = float2(bin + 0.5) / 2048.0;
    return float4(texel.x * 2 - 1, texel.y * 2 - 1, 0, 1);
}

float VectorscopeScatterPS(in float4 vpos : SV_Position) : SV_Target0 {return 1;}

void TitleVectorscopePS(in VSOUT i, out float4 o : SV_Target0)
{
    if(EXT_SCOPE_MODE != SCOPE_MODE_VECTORSCOPE && EXT_SCOPE_MODE != SCOPE_MODE_VECTORSCOPE_2X)
        discard;
    //title scope tex is 1024x512
    //our raw scope is 2048x2048

    int2 p = int2(i.vpos.xy);
    o = 0;

    if(p.x < 512)
    {
        for(int x = 0; x < 4; x++)
        for(int y = 0; y < 4; y++)
            o += tex2Dfetch(sVectorscopeTex, p + 512 * int2(x, y)).x;
        o *= 1000.0 / (VECTORSCOPE_SAMPLES_X * VECTORSCOPE_SAMPLES_Y);
        float2 pbpr = (p + 0.5) / 512.0 * 2 - 1;
        pbpr = EXT_SCOPE_MODE == SCOPE_MODE_VECTORSCOPE_2X ? pbpr * 0.5 : pbpr;
        float3 tint_color = ypbpr_to_rgb(float3(1.0, pbpr.x, -pbpr.y));      
        o.rgb *= tint_color;
        o.rgb /= 1.0 + o.rgb;      
    } 

    o.w = 1;   
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_ReGradePlus
<
    ui_label = "iMMERSE Ultimate: ReGrade+";
>
{ 
    pass { VertexShader = ColorModeVS; PixelShader = ColorModeLUTGenAPS; RenderTarget = ReGradePlusLUTTexA;}
    pass { VertexShader = ColorModeVS; PixelShader = ColorModeLUTGenBPS; RenderTarget = ReGradePlusLUTTexB;}
    pass { VertexShader = ColorModeVS; PixelShader = ColorModeApplyPS; }
        
    pass { VertexShader = BWModeVS; PixelShader = BWModeLUTGenAPS; RenderTarget = ReGradePlusLUTTexA;}
    pass { VertexShader = BWModeVS; PixelShader = BWModeCloneBackbufferPS; RenderTarget = ReGradePlusBackbufferClone;}
    pass { VertexShader = BWModeVS; PixelShader = BWModeApplyPS; }    
}

technique MartysMods_ReGradePlusHistogram
<
    ui_label = "iMMERSE Ultimate: ReGrade+ Histogram";
>
{
#if _COMPUTE_SUPPORTED 
    pass
    {
        ComputeShader = WaveformCS<1, 1024>;
    	DispatchSizeX = NUM_COLUMNS_X;
    	DispatchSizeY = 1;   
    } 
    pass
    {
        ComputeShader = WaveformToHistogramCS<1, 256>;
    	DispatchSizeX = 256;
    	DispatchSizeY = 1; 
    }
#else //look what they have to do to mimic a fraction of our power...
   pass
	{
		VertexShader = WaveformVS;
		PixelShader = WaveformPS;
		RenderTarget = ReGradePlusWaveformTex;
		PrimitiveTopology = POINTLIST;
		VertexCount = NUM_SAMPLES_Y * NUM_SAMPLES_X * 4;
		ClearRenderTargets = true; 
		BlendEnable = true; 
		SrcBlend = ONE; 
		DestBlend = ONE;
		SrcBlendAlpha = ONE;
		DestBlendAlpha = ONE;
    }    
    pass
	{
		VertexShader = MainVS;
		PixelShader = WaveformFlattenIntermediatePS;
		RenderTarget = ReGradePlusWaveformReduceTexIntermediate;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader = WaveformFlattenFinalPS;
		RenderTarget = ReGradePlusHistogramTex;
	}
#endif //_COMPUTE_SUPPORTED

    pass { VertexShader = MainVS; PixelShader = TitleHistogramPS; RenderTarget = API_TEX_HISTOGRAM_TITLE;} 
    pass { VertexShader = MainVS; PixelShader = TitleWaveformPS; RenderTarget = API_TEX_SCOPE_TITLE;} 
    pass { VertexShader = MainVS; PixelShader = VectorscopeClearBlockPS; RenderTarget = VectorscopeTex;} 
    pass
	{
		VertexShader = VectorscopeScatterVS;
		PixelShader = VectorscopeScatterPS;
        RenderTarget = VectorscopeTex;
		PrimitiveTopology = LINELIST;
		VertexCount = VECTORSCOPE_SAMPLES_X * VECTORSCOPE_SAMPLES_Y;
		//ClearRenderTargets = true; 
		BlendEnable = true; 
		SrcBlend = ONE; 
		DestBlend = ONE;
		SrcBlendAlpha = ONE;
		DestBlendAlpha = ONE;
    }

    pass { VertexShader = MainVS; PixelShader = TitleVectorscopePS; RenderTarget = API_TEX_SCOPE_TITLE;} 
}
