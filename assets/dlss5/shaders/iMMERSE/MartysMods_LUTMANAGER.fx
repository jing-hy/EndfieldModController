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

    LUT Manager companion shader

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/


/*=============================================================================
	UI Uniforms
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

uniform bool UPSAMPLE_LUT <
    ui_label = "Enhanced LUT Quality";
    ui_tooltip = "Increases LUT precision for low resolution LUTs dramatically\nby magnifying with a very high quality but expensive upsampling method.\n\nThe resulting LUT is sampled normally at runtime,\nto avoid using the expensive method for every screen pixel.\n\nUse this for LUT resolutions < 32x32x32 for best results.";
> = true;

uniform bool SHOW_LUT_PREVIEW <
    ui_label = "Show all LUTs in current atlas side by side";
> = false;

uniform float LUT_BLEND_INTENSITY_CHROMA <
	ui_type = "slider";
	ui_min = 0.0; ui_max = 1.0;
    ui_label = "Blend Intensity (Chroma)";
> = 1.0;
uniform float LUT_BLEND_INTENSITY_LUMA <
	ui_type = "slider";
	ui_min = 0.0; ui_max = 1.0;
    ui_label = "Blend Intensity (Luma)";
> = 1.0;

/*=============================================================================
	Textures, Samplers, Globals, Structs
=============================================================================*/

texture LUTManagerSrc : MARTY_LUT_MANAGER;
sampler2D sLUTManagerSrc { Texture = LUTManagerSrc;   };

texture ColorInputTex : COLOR;
sampler ColorInput 	{ Texture = ColorInputTex; };

uniform int3 LUT_DESC < source = "marty_lut_desc"; >;

//CRC64 hash of LUT Atlas filename, saved as 2x uint32
uniform uint2 LUT_MANAGER_SOURCE_ATLAS      < hidden = true; >  = uint2(0, 0);
uniform int LUT_MANAGER_ATLAS_IDX           < hidden = true; >  = 0;

uniform uint LUT_MANAGER_ATLAS_TILE_SIZE    < hidden = true; >  = 0;
uniform uint LUT_MANAGER_ATLAS_TILE_AMT     < hidden = true; >  = 0;

#define LUT_DIMS uint3(LUT_MANAGER_ATLAS_TILE_SIZE, LUT_MANAGER_ATLAS_TILE_SIZE, LUT_MANAGER_ATLAS_TILE_AMT)
 
#define LUT_DIM_R    51 
#define LUT_DIM_G    84
#define LUT_DIM_B    51

texture2D LUTManagerHD	{ Width = LUT_DIM_R * LUT_DIM_B; Height = LUT_DIM_G; Format = RGBA32F; };
sampler2D sLUTManagerHD	{ Texture = LUTManagerHD;   };



struct VSOUT
{
	float4                  vpos        : SV_Position;
    float2                  uv          : TEXCOORD0;    
};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_texture.fxh"
#include ".\MartysMods\mmx_colorspaces.fxh"

/*=============================================================================
	Functions
=============================================================================*/

float3 draw_lut(float2 coord, int3 volumesize) //need float2 due to DX9 being a jackass
{
    coord.y %= volumesize.y;
    float3 col = float3(coord.x % volumesize.x, coord.y, floor(coord.x / volumesize.x));
    col = saturate(col / (volumesize - 1.0));
    return saturate(col);
}

float4 tex3D(sampler s, float3 uvw, int3 size, int atlas_idx)
{
    uvw = saturate(uvw);
    uvw = uvw * size - uvw;
    uvw.xy = (uvw.xy + 0.5) / size.xy;
    
    float zlerp = frac(uvw.z);
    uvw.x = (uvw.x + uvw.z - zlerp) / size.z;

    float2 uv_a = uvw.xy;
    float2 uv_b = uvw.xy + float2(1.0/size.z, 0);
    
    int atlas_size = tex2Dsize(s).y / size.y;
    uv_a.y = (uv_a.y + atlas_idx) / atlas_size;
    uv_b.y = (uv_b.y + atlas_idx) / atlas_size;

    return lerp(tex2Dlod(s, uv_a, 0), 
                tex2Dlod(s, uv_b, 0),
                zlerp); 
}

float4 tex3D_cubic(sampler s, float3 uvw, int3 size, int atlas_idx)
{
    //end condition, no way to handle this easily without potentially introducing wrong values    
    if(any(abs(uvw - 0.5) > 0.5 - rcp(size) * 0.5))
        return tex3D(s, uvw, size, atlas_idx);

    uvw = saturate(uvw) * size;
    float3 tc = floor(uvw - 0.5) + 0.5;

    float3 f = uvw - tc;
    float3 f2 = f * f;
    float3 f3 = f2 * f;

    float3 w0 = f2 - 0.5 * (f3 + f);
    float3 w1 = 1.5 * f3 - 2.5 * f2 + 1;
    float3 w3 = 0.5 * (f3 - f2);

    float3 s0 = w0 + w1; 

    float3 t0 = tc - 1 + w1 / s0;
    float3 t1 = tc + 1 + w3 / (1 - s0); 

    t0 /= size; t1 /= size;

    float4 X00 = lerp(tex3D(s, float3(t1.x, t0.y, t0.z), size, atlas_idx),
                      tex3D(s, float3(t0.x, t0.y, t0.z), size, atlas_idx), s0.x);

    float4 X10 = lerp(tex3D(s, float3(t1.x, t1.y, t0.z), size, atlas_idx),
                      tex3D(s, float3(t0.x, t1.y, t0.z), size, atlas_idx), s0.x);

    float4 XX0 = lerp(X10, X00,  s0.y);

    float4 X01 = lerp(tex3D(s, float3(t1.x, t0.y, t1.z), size, atlas_idx),
                      tex3D(s, float3(t0.x, t0.y, t1.z), size, atlas_idx), s0.x);

    float4 X11 = lerp(tex3D(s, float3(t1.x, t1.y, t1.z), size, atlas_idx),
                      tex3D(s, float3(t0.x, t1.y, t1.z), size, atlas_idx), s0.x);

    float4 XX1 = lerp(X11, X01,  s0.y);
    return lerp(XX1, XX0,  s0.z);
}

/*=============================================================================
	Shader Entry Points
=============================================================================*/

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv.xy);
    return o;
}

void LUTUpsamplePS(in VSOUT i, out float4 o : SV_Target0)
{
    if(!UPSAMPLE_LUT) discard;
    o.rgb = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    o.w = 1;
    o = float4(tex3D(sLUTManagerSrc, o.rgb, LUT_DIMS, LUT_MANAGER_ATLAS_IDX).rgb, 1);
}

//we need correct downsampling so the preview tiles don't alias like crazy
//but we also don't need to repeat the computation across the entire screen
void MakePreviewTilePS(in VSOUT i, out float3 o : SV_Target0)
{   
    if(!SHOW_LUT_PREVIEW || dot(tex2Dsize(sLUTManagerSrc).xy, 0.5) < 2) discard;    

    int num_luts_in_atlas = tex2Dsize(sLUTManagerSrc).y / LUT_DIMS.x;
    int best_fit_num_x = ceil(sqrt(num_luts_in_atlas));
    best_fit_num_x = min(best_fit_num_x, 16);

    int2 p = int2(i.vpos.xy);
    if(any(p > BUFFER_SCREEN_SIZE / best_fit_num_x))
    {
        discard;
    }

    o = 0;
    [loop]for(int x = 0; x <= best_fit_num_x; x++)
    [loop]for(int y = 0; y <= best_fit_num_x; y++)
        o += tex2Dfetch(ColorInput, p * best_fit_num_x + int2(x, y)).rgb;
    o /= best_fit_num_x*best_fit_num_x;
}

void LUTApplyPS(in VSOUT i, out float3 o : SV_Target0)
{
    if(dot(tex2Dsize(sLUTManagerSrc).xy, 0.5) < 2) discard; 

    float3 c = tex2D(ColorInput, i.uv).rgb;
    c = saturate(c);

    [branch]
    if(UPSAMPLE_LUT)
        o = Texture::sample3D_tetrahedral(sLUTManagerHD, c, int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B), 0).rgb;    
    else     
        o = Texture::sample3D_tetrahedral(sLUTManagerSrc, c, LUT_DIMS, LUT_MANAGER_ATLAS_IDX).rgb;
    
    //OKLab seems to be most consistent in what it does to the colors
    float3 oklab_i = Colorspace::rgb_to_oklab(c);
    float3 oklab_o = Colorspace::rgb_to_oklab(o);
    float3 oklab_merged = lerp(oklab_i, oklab_o, float3(LUT_BLEND_INTENSITY_LUMA, LUT_BLEND_INTENSITY_CHROMA, LUT_BLEND_INTENSITY_CHROMA));
    o = saturate(Colorspace::oklab_to_rgb(oklab_merged));

    if(SHOW_LUT_PREVIEW) 
    { 
        int num_luts_in_atlas = tex2Dsize(sLUTManagerSrc).y / LUT_DIMS.x;
        int best_fit_num_x = ceil(sqrt(num_luts_in_atlas));

        float2 tile_uv = i.uv * best_fit_num_x;
        float2 in_tile_uv = frac(tile_uv);

        uint2 tile_coord = uint2(tile_uv);
        uint flat_idx = tile_coord.y + tile_coord.x * best_fit_num_x;                

        if(flat_idx < num_luts_in_atlas)
        {
            c = tex2Dlod(ColorInput, in_tile_uv / best_fit_num_x, 0).rgb;     
            o = Texture::sample3D_tetrahedral(sLUTManagerSrc, c, LUT_DIMS, flat_idx).rgb;

            //OKLab seems to be most consistent in what it does to the colors
            float3 oklab_i = Colorspace::rgb_to_oklab(c);
            float3 oklab_o = Colorspace::rgb_to_oklab(o);
            float3 oklab_merged = lerp(oklab_i, oklab_o, float3(LUT_BLEND_INTENSITY_LUMA, LUT_BLEND_INTENSITY_CHROMA, LUT_BLEND_INTENSITY_CHROMA));
            o = saturate(Colorspace::oklab_to_rgb(oklab_merged));

            [branch]
            if(flat_idx == LUT_MANAGER_ATLAS_IDX)
            {
                float2 norm_uv = abs(in_tile_uv * 2.0 - 1.0);
                float diff = norm_uv.x * BUFFER_ASPECT_RATIO.y + norm_uv.y - BUFFER_ASPECT_RATIO.y;
                float highlight = step(0.7, diff);
                //highlight += dot(1, smoothstep(1.0 - fwidth(norm_uv) * 3, 1.0 - fwidth(norm_uv), norm_uv));
                o = lerp(o, 1, saturate(highlight));
            }
        }
        else o = 0;
    }   
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_LutManager
<
    ui_label = "iMMERSE Ultimate: LUT-Manager";
    ui_tooltip =        
        "                              MartysMods - LUT Manager                            \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "Companion Shader for the LUT Manager ReShade 6+ addon. Enable this effect and set \n"
        "the desired LUT in the addon interface to apply custom color styles.              \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n";
>
{
    pass    
	{
		VertexShader = MainVS;
		PixelShader = LUTUpsamplePS;
        RenderTarget = LUTManagerHD;
	}
    pass    
	{
		VertexShader = MainVS;
		PixelShader = MakePreviewTilePS;
	}
    pass    
	{
		VertexShader = MainVS;
		PixelShader = LUTApplyPS;
	} 
}