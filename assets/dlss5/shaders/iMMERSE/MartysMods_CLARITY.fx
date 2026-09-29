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

    Clarity

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

uniform float EFFECT_RADIUS <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Effect Radius";
> = 0.5;

uniform float TEXTURE_INTENSITY <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Texture Intensity";
	ui_category = "Blending";
> = 0.0;

uniform float HDR_INTENSITY <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Local Contrast Intensity";
	ui_category = "Blending";
> = 0.0;

uniform bool DEPTH_MOD <
    ui_label = "Use Depth Separation";
	ui_category = "Depth Separation";
> = false;

uniform bool DEPTH_MOD_SHOW <
    ui_label = "Show Depth Separation";
	ui_category = "Depth Separation";
> = false;

uniform float FG_BG_BALANCE <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Foreground/Background Balance";
	ui_category = "Depth Separation";
> = 0.5;

uniform float TEXTURE_INTENSITY_FG <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Texture Intensity FG";
	ui_category = "Depth Separation";
> = 0.0;

uniform float HDR_INTENSITY_FG  <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Local Contrast Intensity FG";
	ui_category = "Depth Separation";
> = 0.0;

uniform float TEXTURE_INTENSITY_BG <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Texture Intensity BG";
	ui_category = "Depth Separation";
> = 0.0;

uniform float HDR_INTENSITY_BG  <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Local Contrast Intensity BG";
	ui_category = "Depth Separation";
> = 0.0;
/*
uniform float4 tempF1 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
    ui_category = "Internal Parameters"; 
> = float4(1,1,1,1);

uniform float4 tempF2 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
    ui_category = "Internal Parameters"; 
> = float4(1,1,1,1);

uniform float4 tempF3 <
    ui_type = "drag";
    ui_min = -100.0;
    ui_max = 100.0;
    ui_category = "Internal Parameters"; 
> = float4(1,1,1,1);
*/
/*=============================================================================
	Textures, Samplers, Globals
=============================================================================*/

texture ColorInputTex : COLOR;
texture DepthInputTex : DEPTH;
sampler ColorInput 	{ Texture = ColorInputTex; };
sampler DepthInput  { Texture = DepthInputTex; };

texture2D ClarityBlurPyramidA	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidA 	{ Texture = ClarityBlurPyramidA;};
texture2D ClarityBlurPyramidB	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidB 	{ Texture = ClarityBlurPyramidB;};
texture2D ClarityBlurPyramidC	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidC 	{ Texture = ClarityBlurPyramidC;};
texture2D ClarityBlurPyramidD	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidD 	{ Texture = ClarityBlurPyramidD;};
texture2D ClarityBlurPyramidE	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidE 	{ Texture = ClarityBlurPyramidE;};
texture2D ClarityBlurPyramidF	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidF 	{ Texture = ClarityBlurPyramidF;};
texture2D ClarityBlurPyramidG	{ Width = BUFFER_WIDTH>>1;   Height = BUFFER_HEIGHT>>1;  Format = R16F;  	};
sampler2D sClarityBlurPyramidG 	{ Texture = ClarityBlurPyramidG;};


struct VSOUT
{
	float4 vpos : SV_Position;
    float2 uv   : TEXCOORD0;
};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_depth.fxh"
#include ".\MartysMods\mmx_texture.fxh"

/*=============================================================================
	Functions
=============================================================================*/

#define degamma(_v) ((_v)*0.283799*((2.52405+(_v))*(_v)))
#define regamma(_v) (1.14374*(-0.126893*(_v)+sqrt(_v)))


float blend_pg_leveltransfer(float base, float blend)
{
	return pow(abs(blend), exp2((blend - base) * 5.0));
}


float blend_soft_light(float base, float blend)
{	
	return (1.0 - 2 * blend) * base * base + 2 * base * blend;
}

float layerweight(float i)
{
    return exp2(-i * 0.5 * (1 - sqrt(EFFECT_RADIUS)));
}

float atrous_down(sampler2D tex, float2 uv, int iteration)
{
	float2 src_size = tex2Dsize(tex);
	float2 offs = 1.0 / src_size;

	float center = tex2D(tex, uv).r;
	float2 sum = float2(center, 1);

	[unroll]for(int x = -1; x <= 1; x++)
	[unroll]for(int y = -1; y <= 1; y++)
	{
		if(x == 0 && y == 0) continue;

		float tap = tex2D(tex, uv + offs * float2(x, y) * exp2(iteration)).r;		
		float diff = abs(tap - center)/(min(tap, center) + 0.0001);
		float w = exp2(-diff * diff * 0.25);
		sum += float2(tap, 1) * w;
	}
	return sum.x / sum.y;
}

float atrous_initial(sampler2D tex, float2 uv, int iteration)
{
	float2 src_size = tex2Dsize(tex);
	float2 offs = 1.0 / src_size;

	float3 center = tex2D(tex, uv).rgb; 
	center = degamma(center);  
	float vc = dot(center, float3(0.2126, 0.7152, 0.0722));  
	float2 sum = float2(vc, 1);

	[unroll]for(int x = -1; x <= 1; x++)
	[unroll]for(int y = -1; y <= 1; y++)
	{
		if(x == 0 && y == 0) continue;

		float3 tap = tex2D(tex, uv + offs * float2(x, y) * exp2(iteration)).rgb;
		tap = degamma(tap); 		
		float vt = dot(tap, float3(0.2126, 0.7152, 0.0722));		
		float diff = abs(vc - vt)/(min(vc, vt) + 0.0001);
		float w =  exp2(-diff * diff * 0.25);
		sum += float2(vt, 1) * w;
	}
	return sum.x / sum.y;
}

/*=============================================================================
	Shader entry points
=============================================================================*/

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); //use original fullscreen triangle VS
    return o;
}

void BlurI(  in VSOUT i, out float o : SV_Target0) { o = atrous_initial(ColorInput, i.uv, 0); }
void Blur0(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidA, i.uv, 0); }
void Blur1(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidB, i.uv, 1); }
void Blur2(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidC, i.uv, 2); }
void Blur3(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidD, i.uv, 3); }
void Blur4(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidE, i.uv, 4); }
void Blur5(  in VSOUT i, out float o : SV_Target0) { o = atrous_down(sClarityBlurPyramidF, i.uv, 5); }

void MainPS(in VSOUT i, out float3 o : SV_Target0)
{
	float2 effect_intensity = float2(TEXTURE_INTENSITY, HDR_INTENSITY);	

	if(DEPTH_MOD)
	{
		float z = Depth::get_linear_depth(i.uv);
		float bias = FG_BG_BALANCE * 2.0 - 1.0;
		float2 t; //pg21: exponent linearized curve function. |x-f(x, b)| = |x-f(x, -b)|
		t.x =       pow(saturate(z      ), 1.0 + bias *  2.0);
		t.y = 1.0 - pow(saturate(1.0 - z), 1.0 - bias * 16.0);
		float balance = bias > 0 ? t.x : t.y;
		balance = saturate(balance * 1.25 - 0.125); //clip on both sides

		effect_intensity = lerp(float2(TEXTURE_INTENSITY_FG, HDR_INTENSITY_FG), float2(TEXTURE_INTENSITY_BG, HDR_INTENSITY_BG), balance);

		if(DEPTH_MOD_SHOW)
		{
			o = balance;
			return;
		}	
	}

	
	float luma_lowestoctave = Texture::sample2D_bspline_auto(sClarityBlurPyramidE, i.uv).x;
	float2 luma_octaves = float2(luma_lowestoctave, 1) * layerweight(7);
	luma_octaves += float2(tex2D(sClarityBlurPyramidF, i.uv).x, 1) * layerweight(6);
	luma_octaves += float2(tex2D(sClarityBlurPyramidE, i.uv).x, 1) * layerweight(5);
	luma_octaves += float2(Texture::sample2D_bspline_auto(sClarityBlurPyramidD, i.uv).x, 1) * layerweight(4);
	luma_octaves += float2(Texture::sample2D_bspline_auto(sClarityBlurPyramidC, i.uv).x, 1) * layerweight(3);
	luma_octaves += float2(Texture::sample2D_bspline_auto(sClarityBlurPyramidB, i.uv).x, 1) * layerweight(2);
	luma_octaves += float2(Texture::sample2D_bspline_auto(sClarityBlurPyramidA, i.uv).x, 1) * layerweight(1);
	luma_octaves.x /= luma_octaves.y;

	luma_octaves.x = regamma(luma_octaves.x);
	luma_lowestoctave = regamma(luma_lowestoctave);
	
	o = tex2D(ColorInput, i.uv).rgb;
	float luma_src = regamma(dot(degamma(o), float3(0.2126, 0.7152, 0.0722)));
	float mask = abs(luma_lowestoctave - luma_src);

	effect_intensity *= exp2(-mask * float2(16.0, 8.0)) * float2(1.0, 0.7); //different tunings for HDR

	o *= lerp(1, luma_octaves.x / (luma_src + 1e-6), -effect_intensity.x);
	luma_src = regamma(dot(degamma(o), float3(0.2126, 0.7152, 0.0722)));
	luma_octaves.x = blend_soft_light(luma_octaves.x, luma_src);
	o *= lerp(1, luma_octaves.x / (luma_src + 1e-6), -effect_intensity.y);	 
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_Clarity
<
    ui_label = "iMMERSE Pro: Clarity";
    ui_tooltip =        
        "                               MartysMods - Clarity                               \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "Clarity allows to enhance texture and image details, by adjusting local contrast. \n"
        "This allows to add a soft glow or sharp, gritty textures without haloing or noise.\n" 
		"\n"
		"Using the foreground/background separation, the background can be softened without\n"
		"using a depth of field effect, bringing attention to the image subject.           \n"      
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n";
>
{
	pass{VertexShader = MainVS;   PixelShader = BlurI;   RenderTarget = ClarityBlurPyramidA; }
	pass{VertexShader = MainVS;   PixelShader = Blur0;   RenderTarget = ClarityBlurPyramidB; }
	pass{VertexShader = MainVS;   PixelShader = Blur1;   RenderTarget = ClarityBlurPyramidC; }
	pass{VertexShader = MainVS;   PixelShader = Blur2;   RenderTarget = ClarityBlurPyramidD; }
	pass{VertexShader = MainVS;   PixelShader = Blur3;   RenderTarget = ClarityBlurPyramidE; }
	pass{VertexShader = MainVS;   PixelShader = Blur4;   RenderTarget = ClarityBlurPyramidF; }
	pass{VertexShader = MainVS;   PixelShader = Blur5;   RenderTarget = ClarityBlurPyramidG; }
	pass{VertexShader = MainVS;   PixelShader = MainPS;	}
}
