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

    Physically based Depth of Field

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding  	

=============================================================================*/

/*
    todo:    
 
    bokeh scatter  
*/

/*=============================================================================
	Preprocessor settings
=============================================================================*/

#ifndef DOF_FULL_RESOLUTION
 #define DOF_FULL_RESOLUTION                0   //[0 or 1]      If enabled, the DOF will render its effects in fullscreen, otherwise half res (default)
#endif

#ifndef DOF_ADVANCED_BOKEH_EFFECTS
 #define DOF_ADVANCED_BOKEH_EFFECTS         0   //[0 or 1]      If enabled, more features for bokeh shapes become available, at a performance cost
#endif

//no touchy >:(
#define MIN_F_STOPS 		0.95		
#define MAX_F_STOPS 		8.0
#define COC_CLAMP			0.015

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform int FOCUS_MODE <
	ui_type = "combo";
    ui_label = "Focusing Mode";
	ui_items = "Manual Focus\0Autofocus\0Autofocus (Point and Click with MMB)\0";
    ui_category = "Focusing"; 
> = 0;

uniform bool USE_FOCUS_HELPER <
    ui_label = "Enable Focus Helper";
    ui_category = "Focusing"; 
> = false;

uniform float RAW_FOCUS_PLANE_DEPTH <
    ui_type = "drag";
    ui_min = 0.002;
    ui_max = 1.0;
    ui_label = "Manual Focal Plane Depth";
    ui_tooltip = "Distance to the focal plane. 0 means camera itself, 1 means infinity.\nThis value is internally converted to actual distance parameters.\nFor easier adjustment, this parameter reacts more sensitive to close areas.";  
    ui_category = "Focusing"; 
> = 0.1;

//#define FOCUS_PLANE_DEPTH (RAW_FOCUS_PLANE_DEPTH * RAW_FOCUS_PLANE_DEPTH) //Squared for more fine grained control

uniform float2 AUTOFOCUS_CENTER <
    ui_type = "drag";
    ui_min = -1.0; ui_max = 1.0;
    ui_label = "Autofocus Center";
    ui_tooltip = "X and Y coordinates of autofocus center. Negative values move left/up";
    ui_category = "Focusing";
> = float2(0.0, 0.0);

uniform float AUTOFOCUS_RANGE <
    ui_type = "drag";
    ui_min = 0.05;
    ui_max = 1.0;
    ui_label = "Autofocus Detection Range";
    ui_tooltip = "Area size around focus center to analyze";
    ui_category = "Focusing";
> = 0.35;

uniform float AUTOFOCUS_SPEED <
    ui_type = "drag";
    ui_min = 0.05;
    ui_max = 1.0;
    ui_label = "Autofocus Adjustment Speed";
    ui_tooltip = "Adjustment speed of autofocus on focus change";
    ui_category = "Focusing";
> = 0.1;

uniform float FOCAL_LENGTH <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 350.0;
    ui_label = "Focal Length";
    ui_tooltip = "Focal length of the virtual camera. As with real cameras,\na higher focal length means smaller depth of field and more blur.";  
    ui_category = "Lens Parameters - Simple"; 
> = 50.0;

uniform float FSTOPS <
    ui_type = "drag";
    ui_min = MIN_F_STOPS;
    ui_max = MAX_F_STOPS;
    ui_label = "Aperture F-Stops";
    ui_tooltip = "Aperture size of the virtual camera (4 means f/4). The aperture opening directly influences\nthe bokeh shape curvature and the blur radius.";  
    ui_category = "Lens Parameters - Simple"; 
> = 2.8;

uniform float2 BLUR_INT_FG_BG <
    ui_label = "Foreground/Background Blur Multiplier";
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_tooltip = "Additional non-physically correct blur multiplier to e.g. mask out foreground or background blur.";
    ui_category = "Lens Parameters - Simple"; 
> = float2(1.0, 1.0);

uniform int VERTEX_COUNT <
    ui_type = "slider";
    ui_min = 3;
    ui_max = 9;
    ui_label = "Aperture Blade Count";
    ui_tooltip = "Number of blades of the aperture. For small aperture, e.g. 6 results in hexagonal bokeh.";  
    ui_category = "Lens Parameters - Simple";   
> = 6;

uniform float APERTURE_ROUNDNESS <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Aperture Roundness";
    ui_tooltip = "A value of 0.0 produces polygonal bokeh, a value of 1.0 produces circular bokeh.";  
    ui_category = "Lens Parameters - Simple"; 
> = 1.0;

uniform float BOKEH_ANGLE <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Bokeh Rotation";
    ui_tooltip = "Rotation angle of bokeh shape. Only rotates the polygon shape, scaling is applied after.";
    ui_category = "Lens Parameters - Advanced";  
> = 0.25;

#if DOF_ADVANCED_BOKEH_EFFECTS != 0
uniform float BOKEH_RATIO_TANGENTIAL <
    ui_type = "drag";
    ui_min = -3.0;
    ui_max = 3.0;
    ui_label = "Tangential Bokeh Scale";
    ui_tooltip = "Scales bokeh shape tangentially. Allows to simulate astigmatism, petzval bokeh effect and more.";  
    ui_category = "Lens Parameters - Advanced"; 
> = 0.0;

uniform float BOKEH_RATIO_SAGITTAL <
    ui_type = "drag";
    ui_min = -3.0;
    ui_max = 3.0;
    ui_label = "Sagittal Bokeh Scale";
    ui_tooltip = "Scales bokeh shape sagittally. Allows to simulate astigmatism, petzval bokeh effect and more.";
    ui_category = "Lens Parameters - Advanced";  
> = 0.0;

uniform float BOKEH_ANAMORPH_RATIO <
    ui_type = "drag";
    ui_min = 1.0;
    ui_max = 3.0;
    ui_label = "Anamorph Bokeh Ratio";
    ui_tooltip = "Squeezes Bokeh horizontally to simulate the usage of anamorphic lenses.\nTechnically, bokeh should increase vertically and not decrease horizontally,\nbut the usage of an anamorphic lens alters the FoV, which this shader cannot modify.\nMatching the FoV using a different focal length results yields the results here.";
    ui_category = "Lens Parameters - Advanced";  
> = 1.0;

uniform float BOKEH_SPHERICAL_ABB <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Spherical Abberation"; 
    ui_category = "Lens Parameters - Advanced"; 
> = 0.0;

uniform int BOKEH_SPHERICAL_ABB_MODE <
	ui_type = "combo";
    ui_label = "Spherical Abberation Mode"; 
	ui_items = "Single Lens\0Doublet\0";
    ui_category = "Lens Parameters - Advanced"; 
> = 0;
#else 
#define BOKEH_SPHERICAL_ABB_MODE 0
#endif

uniform int RING_COUNT_MAX <
    ui_type = "slider";
    ui_min = 3;
    ui_max = 25;
    ui_label = "Bokeh Quality";
    ui_tooltip = "Number of sample rings. Higher values produce smoother and more defined bokeh discs, but cost more performance.\nShader might occasionally sample more than this to prevent undersampling in certain areas.";  
    ui_category = "Blur Parameters"; 
> = 7;

uniform float BOKEH_INTENSITY <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Bokeh Highlight Intensity";
    ui_tooltip = "Higher values produce more pronounced bokeh discs.";  
    ui_category = "Blur Parameters"; 
> = 0.5;

uniform float BOKEH_GAMMA <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 2.0;
    ui_label = "Bokeh Highlight Gamma";
    ui_tooltip = "Higher values produce more pronounced bokeh discs.";  
    ui_category = "Blur Parameters"; 
> = 1.0;

uniform float BOKEH_COLOR_INTENSITY <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Bokeh Color Intensity";
    ui_tooltip = "Higher values produce more intense but possibly oversaturated bokeh discs.";  
    ui_category = "Blur Parameters"; 
> = 0.5;

uniform float BOKEH_SMOOTHNESS <
    ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
    ui_label = "Bokeh Smoothness";
    ui_tooltip = "Further out of focus smoothing to soften bokeh discs and close sample gaps.\nThis is relative to bokeh disc size, and will not blur all out of focus areas the same way.";  
    ui_category = "Blur Parameters"; 
> = 0.0;

uniform bool USE_UNDERSAMPLE_PROTECTION <
    ui_label = "Enable Undersampling Protection";
    ui_category = "Blur Parameters";
> = false;

uniform bool USE_SPRITE_BOKEH <
    ui_label = "Enable Bokeh Sprites";
    ui_category = "Blur Parameters";
> = true;

uniform float SPRITE_BOKEH_AMOUNT <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Sprite Bokeh Percentage";
    ui_tooltip = "Balance Parameter for the amount of bokeh discs to replace with procedural sprites.\nHigher values produce more sprites at the cost of performance.";  
    ui_category = "Blur Parameters"; 
> = 0.0;

uniform int BOKEH_SHAPE_DEBUG <
	ui_type = "combo";
    ui_label = "Bokeh Shape Helper";
	ui_items = "OFF\0Point Grid w/ Scene\0Point Grid\0";
	ui_tooltip = "Helps fine tuning bokeh appearance in case bokeh shapes are badly visible.";
    ui_category = "Internal Parameters"; 
> = 0;
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

uniform uint  FRAMECOUNT  < source = "framecount"; >;
uniform float2 MOUSE_POINT < source = "mousepoint"; >;
uniform bool OVERLAY_OPEN < source = "overlay_open"; >;
uniform float FRAME_TIME < source = "frametime"; >;

#define DILATED_COC_TILE_SIZE   ((BUFFER_WIDTH >> 9) + 2)   //((((4 * BUFFER_WIDTH) / 2048)/2)*2 + 8) 

#if DOF_FULL_RESOLUTION != 0
 #define LAYER_PIXEL_SIZE_SCALE  1.0
#else 
 #define LAYER_PIXEL_SIZE_SCALE  2.0
#endif

//=============================================================================

//need to pull these 2 here because DX9 is a jackass and can only read the first 4 bindings slots in VS
texture2D ProminentBokehTex 		    { Width = BUFFER_WIDTH/LAYER_PIXEL_SIZE_SCALE;   Height = BUFFER_HEIGHT/LAYER_PIXEL_SIZE_SCALE;   Format = RGBA16F; };
sampler2D sProminentBokehTex		    { Texture = ProminentBokehTex;	AddressU = MIRROR; AddressV = MIRROR;};

texture2D FocusTex1			        { Width = 1;   Height = 1;                Format = R16F;  	};
sampler2D sFocusTex1			    { Texture = FocusTex1;  };

texture ColorInputTex : COLOR;
texture DepthInputTex : DEPTH;
sampler ColorInput 	                { Texture = ColorInputTex; };
sampler DepthInput                  { Texture = DepthInputTex; };

texture2D FocusTex16			    { Width = 16;   Height = 16;              Format = R16F;  	};
sampler2D sFocusTex16			    { Texture = FocusTex16;  };
texture2D LastMousePt			    { Width = 1;   Height = 1;                Format = RG16F;  	};
sampler2D sLastMousePt			    { Texture = LastMousePt;  };

texture2D TileCoC 					{ Width = BUFFER_WIDTH/DILATED_COC_TILE_SIZE;   Height = BUFFER_HEIGHT/DILATED_COC_TILE_SIZE;   Format = RGBA16F; };
texture2D DilatedTileCoC 			{ Width = BUFFER_WIDTH/DILATED_COC_TILE_SIZE;   Height = BUFFER_HEIGHT/DILATED_COC_TILE_SIZE;   Format = RGBA16F; };
sampler2D sTileCoC					{ Texture = TileCoC;	    MinFilter = POINT; MagFilter = POINT; MipFilter = POINT;		};
sampler2D sDilatedTileCoC			{ Texture = DilatedTileCoC;	};
sampler2D sDilatedTileCoCPoint		{ Texture = DilatedTileCoC;	 MinFilter = POINT; MagFilter = POINT; MipFilter = POINT;};

texture2D ForegroundTex 			{ Width = BUFFER_WIDTH/LAYER_PIXEL_SIZE_SCALE;   Height = BUFFER_HEIGHT/LAYER_PIXEL_SIZE_SCALE;   Format = RGBA16F; };
sampler2D sForegroundTex			{ Texture = ForegroundTex; };
texture2D BackgroundTex 			{ Width = BUFFER_WIDTH/LAYER_PIXEL_SIZE_SCALE;   Height = BUFFER_HEIGHT/LAYER_PIXEL_SIZE_SCALE;   Format = RGBA16F; };
sampler2D sBackgroundTex			{ Texture = BackgroundTex; };

texture2D ColorAndDepthTex 			{ Width = BUFFER_WIDTH;   Height = BUFFER_HEIGHT;   Format = RGBA16F;};
sampler2D sColorAndDepthTex			{ Texture = ColorAndDepthTex; AddressU = MIRROR; AddressV = MIRROR; };

texture2D ColorAndCOCTex 		    { Width = BUFFER_WIDTH/LAYER_PIXEL_SIZE_SCALE;   Height = BUFFER_HEIGHT/LAYER_PIXEL_SIZE_SCALE;   Format = RGBA16F; };
sampler2D sColorAndCOCTex		    { Texture = ColorAndCOCTex;	AddressU = MIRROR; AddressV = MIRROR;};


texture2D COCTexLo 			        { Width = BUFFER_WIDTH/LAYER_PIXEL_SIZE_SCALE;   Height = BUFFER_HEIGHT/LAYER_PIXEL_SIZE_SCALE;   Format = R16F; };
sampler2D sCOCTexLo			        { Texture = COCTexLo;	AddressU = MIRROR; AddressV = MIRROR;};

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_depth.fxh"
#include ".\MartysMods\mmx_math.fxh"

struct VSOUT
{
	float4 vpos : SV_Position;
    float2 uv : TEXCOORD0;
    float2 camera : TEXCOORD1;
};

struct CSIN 
{
    uint3 groupthreadid     : SV_GroupThreadID;         
    uint3 groupid           : SV_GroupID;            
    uint3 dispatchthreadid  : SV_DispatchThreadID;     
    uint threadid           : SV_GroupIndex;
};

struct TileData
{
    float min_coc;
    float max_coc;
    float min_depth;
    float max_depth;
};

struct BokehKernelData 
{
    float4 vertexmat;
    float2x2 scalemat;
    float2 vertex_curr;
    float2 vertex_next;
};

/*=============================================================================
	Functions
=============================================================================*/

//@return distance in m
float depth_to_z(in float depth)
{
	//z in m
    return depth * RESHADE_DEPTH_LINEARIZATION_FAR_PLANE + 1;
}

//@return focal dist in m
float get_focal_distance() //
{
    return depth_to_z(tex2Dfetch(sFocusTex1, int2(0,0)).x);
	//return depth_to_z(FOCUS_PLANE_DEPTH);
}

float get_coc(VSOUT i, float depth)
{
    float focal_dist = i.camera.y; //unit doesn't matter, since it's cancelled anyways
    float coc_radius_inf = i.camera.x;
    float scene_depth = depth_to_z(depth); //unit doesn't matter, must only be same as focal_dist

    //                     s - d        d: focal distance
    // coc = coc_inf * -----------      s: object distance
    //                       s

    float coc_radius = ((scene_depth - focal_dist) / scene_depth) * coc_radius_inf;
    return coc_radius < 0 ? max(coc_radius * BLUR_INT_FG_BG.x, -COC_CLAMP) : min(coc_radius * BLUR_INT_FG_BG.y, COC_CLAMP);
    //return clamp(coc_radius, -COC_CLAMP * BLUR_INT_FG_BG.x, COC_CLAMP * BLUR_INT_FG_BG.y);
    //return sign(coc_radius) * clamp(abs(coc_radius), 0, COC_CLAMP);
    //return clamp(coc_radius, -COC_CLAMP, 0);
}

float2 get_max_abs_coc(VSOUT i)
{
    return float2(COC_CLAMP, min(COC_CLAMP, i.camera.x)); //foreground CoC will always exceed COC_CLAMP, but far field CoC goes up to radius at infinity
}

float sample_intersect(float coc, float n, float i, float max_radius)
{    
    return saturate(abs(coc) * n / max_radius - i + 0.5); //centered on ring, feather 0.5 both sides
    //return saturate(abs(coc) * n / max_radius - i + 1.0); //this is 1 when coc >= ring radius and 0 when coc <= ring radius - 1, best compromise even though it makes for super small in focus areas...
}

float sample_alpha(float coc)
{
    //float coc_pixels = /*BUFFER_WIDTH/*/coc;
    float coc_pixels = BUFFER_WIDTH*coc/LAYER_PIXEL_SIZE_SCALE;
    return rcp(PI * max(coc_pixels * coc_pixels, 1));
   // return  (rcp(0.007*0.007 + PI * coc_pixels * coc_pixels)); //faster and since it's all relative to each other, it works
}

float get_fg_weight(float coc, TileData Tile)
{
    float weight = saturate(1 - 2.0 * (coc - Tile.min_coc) * rcp(COC_CLAMP));
    return weight;
}

float bokeh_int()
{
   return 1 + exp2(-BOKEH_INTENSITY * 8.0);
}

float3 cone_overlap(float3 c)
{
    float k = saturate(1 - BOKEH_COLOR_INTENSITY) * 0.2;
    float2 f = float2(1 - 2 * k, k);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

float3 cone_overlap_inv(float3 c)
{
    float k = saturate(1 - BOKEH_COLOR_INTENSITY) * 0.2;
    float2 f = float2(k - 1, k) * rcp(3 * k - 1);
    float3x3 m = float3x3(f.xyy, f.yxy, f.yyx);
    return mul(c, m);
}

void unpack_hdr(inout float3 color)
{
    color = cone_overlap(color);
    color = pow(abs(color), exp2(BOKEH_GAMMA));
    float a = bokeh_int(); 
    color = color / (a - color);
    //color = (exp2(tempF3.y * color * color) - 1) / (exp2(tempF3.y) - 1);
}

void pack_hdr(inout float3 color)
{
    color = bokeh_int() * color * rcp(1 + color); 
    // olor = sqrt(log2((exp2(tempF3.y) - 1) * (color - rcp(1 - exp2(tempF3.y)))) / tempF3.y);  
    color = pow(abs(color), exp2(-BOKEH_GAMMA));
    color = cone_overlap_inv(color);
}

float4 tex2Dbicub(sampler tex, float2 iuv, float2 texsize)
{
	float4 uv = 0.0;
	uv.xy = iuv * texsize;

	float2 center = floor(uv.xy - 0.5) + 0.5;
	float4 d = float4(uv.xy - center, 1 + center - uv.xy);
	float4 d2 = d * d;
	float4 d3 = d2 * d;
	float4 sd = d2 * (3 - 2 * d);	

	float4 o = lerp(d2, d3, 0.3594) * 0.2; //approx |err|*255 < 0.2 < bilinear precision
	uv.xy = center - o.zw;
	uv.zw = center + 1 + o.xy;
	uv /= texsize.xyxy;	

	float4 w = (1.0/6.0) + d * 0.5 + sd * (1.0/6.0);
	w = w.wwyy * w.zxzx;

	return w.x * tex2D(tex, uv.xy)
	     + w.y * tex2D(tex, uv.zy)
		 + w.z * tex2D(tex, uv.xw)
		 + w.w * tex2D(tex, uv.zw);
}


TileData init_tile(in VSOUT i)
{
    float4 tile_data = tex2Dbicub(sDilatedTileCoC, i.uv, tex2Dsize(sDilatedTileCoC));
    TileData Tile;
    Tile.min_coc = tile_data.x;
    Tile.max_coc = tile_data.y;
    Tile.min_depth = tile_data.z;
    Tile.max_depth = tile_data.w;
    return Tile;
}

BokehKernelData init_kernel(in float2 uv)
{
    BokehKernelData BokehKernel;
    BokehKernel.vertexmat = Math::get_rotator(TAU / VERTEX_COUNT);

    sincos(radians(360.0 / VERTEX_COUNT) * BOKEH_ANGLE, BokehKernel.vertex_curr.y, BokehKernel.vertex_curr.x);
    BokehKernel.vertex_next = Math::rotate_2D(BokehKernel.vertex_curr, BokehKernel.vertexmat);

    float2 v = uv * (2.0 * BUFFER_ASPECT_RATIO.yx) - BUFFER_ASPECT_RATIO.yx;
    //v.y = -v.y; //fix handedness so v.xy = cos, sin of angle to center
    v.xy /= length(BUFFER_ASPECT_RATIO); //normalize so |v| = 1 in corners
    float r = length(v) + 1e-7; v /= r;

#if DOF_ADVANCED_BOKEH_EFFECTS != 0
    float scale_tangential = r * BOKEH_RATIO_TANGENTIAL;
    float scale_sagittal   = r * BOKEH_RATIO_SAGITTAL;
    float scale_horizontal = rcp(BOKEH_ANAMORPH_RATIO);
    float scale_vertical   = 1.0;

    float2 k = 1.0 + float2(scale_tangential, scale_sagittal);
    float d = (k.x - k.y) * v.x * v.y;

    //rotate * scale A * rotate back * scale B
    BokehKernel.scalemat = float2x2(
        dot(k, v * v) * scale_horizontal,      d,
        d * scale_horizontal,                  dot(k.yx, v * v)
    );
#else 
    BokehKernel.scalemat = float2x2(1,0,0,1);
#endif
    return BokehKernel;
}

float4 get_af_aabb()
{
    float2 focus_uv = AUTOFOCUS_CENTER * 0.5 + 0.5;
    float4 focus_aabb; //sample square window around focal point
    focus_aabb.xy = focus_uv - AUTOFOCUS_RANGE * BUFFER_ASPECT_RATIO * 0.5;
    focus_aabb.zw = focus_uv + AUTOFOCUS_RANGE * BUFFER_ASPECT_RATIO * 0.5;
    focus_aabb = saturate(focus_aabb); //clamp to screen
    return focus_aabb;
}

float3 premultiply_coc(float3 color, float coc)
{
    return color * saturate(abs(coc) / COC_CLAMP + 1/4.0); //TODO investigate why this causes overbrightening close to clipping into camera
}

float3 undo_premultiply_coc(float3 color, float coc)
{
    return color / saturate(abs(coc) / COC_CLAMP + 1/4.0);
}

float spherical_abberation(float ring_idx, float num_rings, float amount)
{
    float x = saturate((ring_idx + 0.5) / num_rings); 
    float x2 = x * x;
    float sh = BOKEH_SPHERICAL_ABB_MODE ? x * (x - x2)*6.7 : x2;
    return lerp(1, amount > 0 ? sh : (1 - sh), abs(amount) * 0.95); //limit so it's never 0
}

/*=============================================================================
	Shader Entry Points
=============================================================================*/

uniform bool MMB_DOWN < source = "mousebutton"; keycode = 2; mode = ""; >;

float4 SaveMouseVS(in uint id : SV_VertexID) : SV_Position
{    
    return float4(!MMB_DOWN, !MMB_DOWN, 0, 1); //faster than discard because this kills the write in the geometry stage
}

void SaveMousePS(in float4 vpos : SV_Position, out float2 o : SV_Target0)
{ 
    o = MOUSE_POINT;
}

float4 FocusVS(in uint id : SV_VertexID) : SV_Position
{ 
    float2 uv; float4 vpos;
    uv.x = (id == 2) ? 2.0 : 0.0;
    uv.y = (id == 1) ? 2.0 : 0.0;
	vpos = float4(uv.xy * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return vpos;
}

void FocusReduce16PS(in float4 vpos : SV_Position, out float o : SV_Target0)
{ 
    if(FOCUS_MODE != 1)
        discard;
   
    float4 focus_aabb = get_af_aabb();
    float2 aabb_span = focus_aabb.zw - focus_aabb.xy;

    int2 samples = ceil(aabb_span * 16 * BUFFER_ASPECT_RATIO); //sample at most 5 samples vertically = 80 because it's 16 threads doing it

    float2 grid_shift = (floor(vpos.xy) + 0.5) / 16.0;
    float2 focus = 0;

    [loop]for(int x = 0; x < samples.x; x++)
    [loop]for(int y = 0; y < samples.y; y++)
    {
        float2 grid_uv_norm = (float2(x, y) + grid_shift) / samples;
        float2 grid_uv_screen = lerp(focus_aabb.xy, focus_aabb.zw, grid_uv_norm);

        float z = Depth::get_linear_depth(grid_uv_screen);

        //real cameras measure contrast, which is inversely proportional to "how much out of focus is it"
        //as such, avg of depth doesn't work, because far depths can be hugely out of focus (30m vs infinity focus) and still be sharp
        //but for close areas, the tiniest focal change results in a big blur. So the weighting must be proportional to the influence
        //changes to the focus plane have on this pixel. Which is the steepness of the CoC curve, which is proportional to 1/(depth^2).
        float w = rcp(z * z + 1e-6); 

        w *= exp2(-dot(grid_uv_norm * 2 - 1, grid_uv_norm * 2 - 1) * 4.0); //weight samples outside from center less
        focus += float2(z, 1) * w;
    }

    o = focus.x / focus.y;
}

void FocusReduce1PS(in float4 vpos : SV_Position, out float4 o : SV_Target0)
{ 
    if(FOCUS_MODE == 0)
    {
        o.xyz = RAW_FOCUS_PLANE_DEPTH * RAW_FOCUS_PLANE_DEPTH;
        o.w = 1;
        return;
    }

    if(FOCUS_MODE == 2)
    {
        o.xyz = Depth::get_linear_depth(tex2Dfetch(sLastMousePt, int2(0,0)).xy * BUFFER_PIXEL_SIZE);
        o.w = 1;
        return;
    }

    float focus = 0;
    float minfocus = 10000;

    for(uint x = 0; x < 16; x++)
    for(uint y = 0; y < 16; y++)
    {
        float f = tex2Dfetch(sFocusTex16, int2(x, y)).x; //tex2Dgather!
        focus += f;
        minfocus = min(f, minfocus);
    }

    o = focus / 256.0;
    o = lerp(o, minfocus, 0.15); //bias towards min a bit
    o.w = saturate(AUTOFOCUS_SPEED * max(FRAME_TIME, 1.0)/50.0);
}

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv); 

    //set up camera parameters
    const float sensor_diag_mm  = 43.3; //mm
    float focal_dist            = get_focal_distance(); //depth -> m
    float focal_dist_mm         = focal_dist * 1000.0; //m -> mm
	float focal_length_mm       = FOCAL_LENGTH; //alternatively: 0.5 * SENSOR_SIZE * rcp(tan(radians(fov_degrees) * 0.5)) //FOV must be diagonal!

	float coc_inf_diameter_mm = focal_length_mm * focal_length_mm * rcp(FSTOPS * (focal_dist_mm - focal_length_mm));	
	float max_coc = 0.5 * coc_inf_diameter_mm / sensor_diag_mm; //unitless screen space % maximum coc radius (at infinity)

    o.camera.x = max_coc;
    o.camera.y = focal_dist;
    
    return o;
}

void MakeInputsPS(in VSOUT i, out float4 o : SV_Target0)
{
    o.rgb = tex2D(ColorInput, i.uv).rgb;unpack_hdr(o.rgb);
	o.a = Depth::get_linear_depth(i.uv); 

    o.rgb = premultiply_coc(o.rgb, get_coc(i, o.w));   

    if(BOKEH_SHAPE_DEBUG)
    {
        float num_img = 10.0;
        float2 uv = (frac((i.uv - 0.5) * num_img * BUFFER_ASPECT_RATIO.yx + 0.5) - 0.5) / num_img;
        o.rgb = length(uv * BUFFER_SCREEN_SIZE.x) < 3.5 ? 32.0 : BOKEH_SHAPE_DEBUG == 1 ? o.rgb : 0.0;
    }     
}

void DownsamplePS(in VSOUT i, out float4 o1 : SV_Target0, out float o2 : SV_Target1)
{
    float4 colordepth = tex2D(sColorAndDepthTex, i.uv);    
    float depth = colordepth.w;
    
    //wz
    //xy
#if DOF_FULL_RESOLUTION != 0
    float max_abs_coc = get_coc(i, depth);
#else
    float4 taps[4];
    taps[0] = tex2D(sColorAndDepthTex, i.uv + float2(-0.5, -0.5) * BUFFER_PIXEL_SIZE);
    taps[1] = tex2D(sColorAndDepthTex, i.uv + float2( 0.5, -0.5) * BUFFER_PIXEL_SIZE);
    taps[2] = tex2D(sColorAndDepthTex, i.uv + float2(-0.5,  0.5) * BUFFER_PIXEL_SIZE);
    taps[3] = tex2D(sColorAndDepthTex, i.uv + float2( 0.5,  0.5) * BUFFER_PIXEL_SIZE);

    float4 cocs;
    cocs.x = get_coc(i, taps[0].w);
    cocs.y = get_coc(i, taps[1].w);
    cocs.z = get_coc(i, taps[2].w);
    cocs.w = get_coc(i, taps[3].w);

    float max_abs_coc = cocs.x;
    max_abs_coc = lerp(max_abs_coc, cocs.y, abs(cocs.y) > abs(max_abs_coc));
    max_abs_coc = lerp(max_abs_coc, cocs.z, abs(cocs.z) > abs(max_abs_coc));
    max_abs_coc = lerp(max_abs_coc, cocs.w, abs(cocs.w) > abs(max_abs_coc));

    float4 w = saturate(1 - 64.0 * abs(max_abs_coc - cocs) / COC_CLAMP);
    colordepth.rgb = taps[0].rgb * w.x 
                   + taps[1].rgb * w.y
                   + taps[2].rgb * w.z
                   + taps[3].rgb * w.w;
    colordepth.rgb /= dot(w, 1); 
#endif
    o1 = colordepth;    
    o2 = o1.w = max_abs_coc;
}

void ExtractProminentBokehShapesPS(in VSOUT i, out float4 o : SV_Target0)
{
    float4 center_color = tex2D(sColorAndCOCTex, i.uv);
    float coc_cutoff = min(COC_CLAMP, i.camera.x) * 0.25; //start mixing in our cool new bokeh at about 25% of maximum blur radius

    if(tex2D(sDilatedTileCoCPoint, i.uv).x < coc_cutoff || !USE_SPRITE_BOKEH){o = 0; return;}

    float center_lum = dot(center_color.rgb, 0.3333);
    float avg_lum = center_lum;

    [unroll]for(int x = -1; x <= 1; x++) 
    [unroll]for(int y = -1; y <= 1; y++) 
    {
        if(x == 0 && y == 0) continue;
        float w = (abs(x) + abs(y)) * 2; //x, 0 or 0, y taps fetch 2 pixels, x, y taps fetch 4 pixels
        avg_lum += w * dot(tex2D(sColorAndCOCTex, i.uv + 1.5 * BUFFER_PIXEL_SIZE * LAYER_PIXEL_SIZE_SCALE * float2(x, y)).rgb, 0.3333); //sample between texels
    }

    avg_lum /= 25.0;

    float brightest_possible = 1 / (1 - bokeh_int());  
    bool is_prominent_pixel = (center_lum - avg_lum) > lerp(-brightest_possible, -brightest_possible*0.01, saturate(SPRITE_BOKEH_AMOUNT));
    o = center_color * is_prominent_pixel;
}

void SubtractShapesFromInputPS(in VSOUT i, out float4 o : SV_Target0)
{
    if(!USE_SPRITE_BOKEH) discard;
    o = tex2D(sProminentBokehTex, i.uv);
}

struct VSOUT2
{
	float4 vpos : SV_Position;
    float2 uv : TEXCOORD0;
    float4 sprite_data : TEXCOORD1;
};

VSOUT2 ScatterVS(in uint id : SV_VertexID)
{
    VSOUT2 o;
    uint sprite_id = id / 3u;
    id %= 3u;

    //map UV to relative triangle size
    o.uv = id.xx == uint2(2, 1) ? 2.0.xx : 0.0.xx;
    //setup triangle shape
    o.vpos.zw = float2(0, 1);
    o.vpos.xy = id.xx == uint2(2, 1) ? 3.0.xx : -1.0.xx;

    o.sprite_data = 0;

    static const uint2 grid_size = uint2(BUFFER_SCREEN_SIZE/LAYER_PIXEL_SIZE_SCALE);
    uint2 screen_texel = uint2(sprite_id % grid_size.x, sprite_id / grid_size.x);
    float2 screen_uv = (screen_texel + 0.5) / grid_size;
    screen_uv = float2(screen_uv.x, 1 - screen_uv.y);

    float4 texel_data = tex2Dfetch(sProminentBokehTex, screen_texel);
    if(texel_data.w < 1e-5) {o.vpos = 1000000; return o;}

    float coc = texel_data.w;
    o.vpos.xy *= coc;
    o.vpos.xy *= BUFFER_ASPECT_RATIO;

#if DOF_ADVANCED_BOKEH_EFFECTS != 0   
    BokehKernelData BokehKernel = init_kernel(screen_uv);
    o.vpos.xy = mul(o.vpos.xy, BokehKernel.scalemat);
#endif
    
    o.vpos.xy += screen_uv;
    o.vpos.xy = o.vpos.xy * 2.0 - 1.0;

    o.sprite_data = float4(undo_premultiply_coc(texel_data.rgb, coc) * sample_alpha(coc), coc);
    return o;
}

void ScatterPS(in VSOUT2 i, out float4 o : SV_Target0)
{
    float2 screen_uv = (i.vpos.xy + 0.5) / float2(BUFFER_SCREEN_SIZE/LAYER_PIXEL_SIZE_SCALE);   

    i.uv = i.uv * 2.0 - 1.0;
    float r = length(i.uv);

    float vertex_angle = TAU / VERTEX_COUNT;
    float ang = -atan2(i.uv.x, i.uv.y) - HALF_PI + BOKEH_ANGLE * vertex_angle; //TODO replace with approximation!!!!
    float centered_angle = frac(ang / vertex_angle) * vertex_angle - vertex_angle * 0.5;//frac(ang / vertex_angle) * vertex_angle - vertex_angle * 0.5;
    
    if(r > 0.01) //avoid singularities of atan2
        r = lerp(cos(centered_angle) * r - cos(vertex_angle * 0.5) + 1.0, r, APERTURE_ROUNDNESS);

    float sdf = r - 1.0; 
    float disc = smoothstep(0, -1, sdf / fwidth(sdf));

#if DOF_ADVANCED_BOKEH_EFFECTS != 0     
    float spherical_abb = spherical_abberation(r * 256.0 + 0.5, 256.0, BOKEH_SPHERICAL_ABB);
    disc *= spherical_abb;    
#endif

    float dest_coc = tex2D(sCOCTexLo, screen_uv).x;
    float w = smoothstep(0, i.sprite_data.w, dest_coc);
    w *= w; w*= w;
    disc *= w;
    o = float4(i.sprite_data.rgb, 0) * disc;
}

void TileCoCPS(in VSOUT i, out float4 o : SV_Target0)
{
	o = float4(1000000, -1000000, 1.0, 0.0);
	float2 srcsize = BUFFER_SCREEN_SIZE; //tex2Dsize(sColorAndDepthTex);

    int2 grid_start = i.vpos.xy * DILATED_COC_TILE_SIZE;

	for(int x = 0; x < DILATED_COC_TILE_SIZE; x++)
	for(int y = 0; y < DILATED_COC_TILE_SIZE; y++)
	{
		float depth = Depth::get_linear_depth(float2(grid_start.x + x, grid_start.y + y) / srcsize.xy);        
        float coc = get_coc(i, depth);

		o.x = min(o.x, coc); 
        o.y = max(o.y, coc);
       
        o.z = min(o.z, depth);
        o.w = max(o.w, depth);
	}
}

void TileDilatePS(in VSOUT i, out float4 o : SV_Target0)
{
    float4 tile_data = tex2Dfetch(sTileCoC, i.vpos.xy);

    //we need to search (gather) the entire maximum CoC radius
    //however, we only need to store the biggest CoC that would be able to scatter onto this one
    float dilate_radius = COC_CLAMP;
    float tile_scale = tex2Dsize(sTileCoC).x;
    int dilate_window_tiles = ceil(dilate_radius * tex2Dsize(sTileCoC).x); //.x because CoC is in % of screen width as per convention
    dilate_window_tiles++; //some padding
    float4 dilated_tile_data = tile_data;

    for(int x = -dilate_window_tiles; x <= dilate_window_tiles; x++)
    for(int y = -dilate_window_tiles; y <= dilate_window_tiles; y++)
    {
        int2 tpos = i.vpos.xy + int2(x, y);
        float4 t = tex2Dfetch(sTileCoC, tpos);
        float curr_abs_coc = max(abs(t.x), abs(t.y));
        float dilate_distance = length(float2(x, y)) / tile_scale; //% of screen width, same as CoC

        //if the coc of the currently sampled tile would be able to scatter onto the current "pixel", take it
        //theoretically, this could be done with max coc for background, and min coc for foreground separately
        if(dilate_distance < curr_abs_coc * 1.5) //padding so the maximum intersectable coc spreads father than it should, to make 100% sure we don't get artifacts
        {
            tile_data.xz = min(tile_data.xz, t.xz); 
            tile_data.yw = max(tile_data.yw, t.yw);
        }
    }

    o = tile_data;
}

struct Accum
{
    float4 color_curr, color_prev;
    float coc_curr, coc_prev;
    float t_curr, t_prev;
    float samples;
};

struct RingAccumulator
{
    float4 color;
    float coc;
    float translucency;
    float samples;
};

void add_sample_to_ring(bool is_first_ring, inout RingAccumulator ring, inout RingAccumulator total, float4 tap, float tap_coc, float tap_weight, float bordering_radius)
{
    const float coc_to_pixels = BUFFER_WIDTH / LAYER_PIXEL_SIZE_SCALE;

    float overlap = (tap_coc - bordering_radius) * coc_to_pixels;
    float belongs_to_prev = saturate(overlap + 0.5);
    belongs_to_prev = is_first_ring ? 0 : belongs_to_prev;
    
    float belongs_to_curr = 1 - belongs_to_prev;     

    total.color += float4(tap.rgb, 1) * tap_weight * belongs_to_prev;
    total.coc += tap_coc * tap_weight * belongs_to_prev;

    ring.color += float4(tap.rgb, 1) * tap_weight * belongs_to_curr;
    ring.coc += tap_coc * tap_weight * belongs_to_curr;

    ring.translucency += saturate(overlap);
    ring.samples++;
}

void merge_rings_and_clear(float ring_count, bool is_first_ring, inout RingAccumulator ring, inout RingAccumulator total)
{
    float coc_to_pixels = BUFFER_WIDTH / LAYER_PIXEL_SIZE_SCALE;

    [branch]
    if(ring.color.w > 0)
    {
        float ring_opacity = saturate(1 - ring.translucency * rcp(ring.samples));
        float prev_coc = total.coc * rcp(total.color.w);
        float curr_coc = ring.coc  * rcp(ring.color.w);
        float occluding = saturate((prev_coc - curr_coc) * coc_to_pixels);

        float prev_factor = total.color.w == 0 ? 0 : saturate(1 - ring_opacity * occluding);
        prev_factor = is_first_ring ? 0 : prev_factor;

        total.color = total.color * prev_factor + ring.color;
        total.coc = total.coc * prev_factor + ring.coc;
    }
    ring.color = ring.coc = ring.samples = ring.translucency = 0;
}

void BokehBackgroundPS(in VSOUT i, out float4 o : SV_Target0)
{
    BokehKernelData BokehKernel = init_kernel(i.uv);
    TileData        Tile        = init_tile(i);

    float scatter_radius_max = Tile.max_coc;
    float scatter_radius_min = min(abs(Tile.max_coc), abs(Tile.min_coc)); 
    float scatter_radius_highestpossible = get_max_abs_coc(i).y;
    int ring_count = ceil(scatter_radius_max / scatter_radius_highestpossible * RING_COUNT_MAX);
    float kernel_radius = float(ring_count) / RING_COUNT_MAX * scatter_radius_highestpossible;  
    ring_count = max(ring_count, 3);

    [branch]
    if(USE_UNDERSAMPLE_PROTECTION)
        ring_count = min(25, ceil(RING_COUNT_MAX * abs(scatter_radius_max) / max(1e-5 + scatter_radius_min, 0.25 * scatter_radius_max)));

    int density_scale = max(1, 6 - VERTEX_COUNT);    

    float4 center = tex2Dlod(sColorAndCOCTex, i.uv, 0); 
    float center_coc = center.w;     

    center.rgb = undo_premultiply_coc(center.rgb, center_coc); 

    if(center_coc * BUFFER_WIDTH * LAYER_PIXEL_SIZE_SCALE <= 0.5)
    {
        o = float4(center.rgb, 0); return;
    }

    bool is_first_ring = true;
    RingAccumulator total, ring;
    total.color = total.coc = total.samples = total.translucency = 0; 
    ring.color = ring.coc = ring.samples = ring.translucency = 0;

    for(float r = ring_count; r >= 1; r--)
    {
        float ring_radius = (kernel_radius * r) / (ring_count + 0.5); 
        float bordering_radius = (kernel_radius * (r + 0.5)) / (ring_count + 0.5);  
#if DOF_ADVANCED_BOKEH_EFFECTS != 0     
        float spherical_abb = spherical_abberation(r, ring_count, BOKEH_SPHERICAL_ABB);
#endif
        for(int v = 0; v < VERTEX_COUNT; v++)
        {            
            for(float s = 0; s < r * density_scale; s++)
            {                
                //aperture roundness
                float h = s / (r * density_scale);
                float b = tan(PI * 2 / VERTEX_COUNT * (h - 0.5));            
                float g = b * (1.0 + BokehKernel.vertexmat.x) / BokehKernel.vertexmat.y * 0.5 + 0.5;
                h = lerp(h, g, APERTURE_ROUNDNESS);

                float2 tap_location = lerp(BokehKernel.vertex_curr, BokehKernel.vertex_next, h);
                tap_location *= (1.0 - APERTURE_ROUNDNESS) + rsqrt(dot(tap_location, tap_location)) * APERTURE_ROUNDNESS; //lerp normalize
#if DOF_ADVANCED_BOKEH_EFFECTS != 0
                tap_location = mul(tap_location, BokehKernel.scalemat);
#endif  
                float4 tap = tex2Dlod(sColorAndCOCTex, i.uv + tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0);
                float tap_coc       = tap.w;                 
                float alpha         = sample_alpha(tap_coc);
                float intersect     = sample_intersect(tap_coc, ring_count, r, kernel_radius); 
                float tap_weight = alpha * intersect; 
   
#if DOF_ADVANCED_BOKEH_EFFECTS != 0               
                tap_weight *= spherical_abb;    
#endif                
                tap.rgb = undo_premultiply_coc(tap.rgb, tap_coc); 
                add_sample_to_ring(is_first_ring, ring, total, tap, tap_coc, tap_weight, bordering_radius);
            }

            BokehKernel.vertex_curr = BokehKernel.vertex_next;
            BokehKernel.vertex_next = Math::rotate_2D(BokehKernel.vertex_curr, BokehKernel.vertexmat);
        }

        merge_rings_and_clear(ring_count, is_first_ring, ring, total);
        is_first_ring = false;
    }
    
    float4 tap = center;
    float tap_coc = center_coc;    
    float alpha = sample_alpha(tap_coc);
    float intersect = 1;
    float tap_weight = alpha * intersect;

#if DOF_ADVANCED_BOKEH_EFFECTS != 0
    tap_weight *= spherical_abberation(0, ring_count, BOKEH_SPHERICAL_ABB);          
#endif
    float bordering_radius = (kernel_radius * 0.5) / (ring_count + 0.5);
    add_sample_to_ring(false, ring, total, tap, tap_coc, tap_weight, bordering_radius);
    merge_rings_and_clear(ring_count, is_first_ring, ring, total);
    
    o.rgb = total.color.rgb / (total.color.w + 1e-7);
    o.w = 1;
}

void BokehForegroundPS(in VSOUT i, out float4 o : SV_Target0)
{
    BokehKernelData BokehKernel = init_kernel(i.uv);  
    TileData       Tile         = init_tile(i);

    float scatter_radius_max = abs(Tile.min_coc);
    float scatter_radius_min = min(abs(Tile.max_coc), abs(Tile.min_coc)); //technically only max coc but the presence of some super big background coc might ruin this    

    float scatter_radius_highestpossible = get_max_abs_coc(i).x;
    uint ring_count = ceil(scatter_radius_max / scatter_radius_highestpossible * RING_COUNT_MAX);
    float kernel_radius = float(ring_count) / RING_COUNT_MAX * scatter_radius_highestpossible;  
    ring_count = max(ring_count, 3);

    [branch]
    if(USE_UNDERSAMPLE_PROTECTION)
        ring_count = min(25, ceil(RING_COUNT_MAX * abs(scatter_radius_max) / max(1e-5 + scatter_radius_min, 0.25 * scatter_radius_max)));

    int density_scale = max(1, 6 - VERTEX_COUNT);

    float4 sum_fg       = 0;
    float4 sum_bg       = 0;
    float4 sum_all      = 0;

    float max_foreground_coc = 0;

    float4 center = tex2Dlod(sColorAndCOCTex, i.uv, 0);
    float center_coc = center.w;
    center.rgb = undo_premultiply_coc(center.rgb, center_coc);

    if(scatter_radius_max < 0.0001)
    {
        o = float4(center.rgb, 0);
        return;
    }

    for(int v = 0; v < VERTEX_COUNT; v++)
    {
        for(float r = 1; r <= ring_count; r++)
        {
#if DOF_ADVANCED_BOKEH_EFFECTS != 0     
            float spherical_abb = spherical_abberation(r, ring_count, -BOKEH_SPHERICAL_ABB); //inverted in foreground
#endif
            for(float s = 0; s < r * density_scale; s++)
            {
                
                //aperture roundness
                float h = s / (r * density_scale);
                float b = tan(PI * 2 / VERTEX_COUNT * (h - 0.5));            
                float g = b * (1.0 + BokehKernel.vertexmat.x) / BokehKernel.vertexmat.y * 0.5 + 0.5;
                h = lerp(h, g, APERTURE_ROUNDNESS);

                float2 tap_location = lerp(BokehKernel.vertex_curr, BokehKernel.vertex_next, h);
                tap_location *= (1.0 - APERTURE_ROUNDNESS) + rsqrt(dot(tap_location, tap_location)) * APERTURE_ROUNDNESS; 
#if DOF_ADVANCED_BOKEH_EFFECTS != 0
                tap_location = mul(tap_location, BokehKernel.scalemat);
#endif
                float ring_radius = (kernel_radius * r) / (ring_count + 0.5);  
                float4 tap = tex2Dlod(sColorAndCOCTex, i.uv - tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0); //- for foreground shape inversion
                
                float tap_coc_orig = tap.w; 
                tap.rgb = undo_premultiply_coc(tap.rgb, tap_coc_orig);

                float mirror_coc = tex2Dlod(sCOCTexLo, i.uv + tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0).x;
                tap.w = min(tap.w, mirror_coc);                    
  
                float tap_coc       = tap.w;            
                float alpha         = sample_alpha(tap_coc);
                float intersect     = sample_intersect(tap_coc, ring_count, r, kernel_radius); 

                float is_foreground = tap_coc < 0 ? 1 : 0;

                float fg_weight = get_fg_weight(tap.w, Tile);
                float bg_weight = 1 - fg_weight;
#if DOF_ADVANCED_BOKEH_EFFECTS != 0
                alpha *= spherical_abb;
#endif
                sum_fg  += float4(tap.rgb, 1) * alpha * intersect * fg_weight * is_foreground;
                sum_bg  += float4(tap.rgb, 1) * alpha * intersect * bg_weight * is_foreground;
                sum_all += float4(tap.rgb, 1) * alpha * sample_intersect(center_coc, ring_count, r, kernel_radius); //fixes a tile bug and sharpens translucent background
                max_foreground_coc = max(max_foreground_coc, -tap_coc * intersect);
            }
        }        
        BokehKernel.vertex_curr = BokehKernel.vertex_next;
        BokehKernel.vertex_next = Math::rotate_2D(BokehKernel.vertex_curr, BokehKernel.vertexmat);
    }

    //center
    float4 orig = tex2Dlod(sColorAndCOCTex, i.uv, 0);
    float4 tap = orig;
    float tap_coc = tap.w;    
    tap.rgb = undo_premultiply_coc(tap.rgb, tap_coc); 
   
    float alpha         = sample_alpha(tap_coc);
    float intersect     = 1.0;
    float is_foreground = tap_coc < 0 ? 1 : 0;

    float fg_weight = get_fg_weight(tap.w, Tile);
    float bg_weight = 1 - fg_weight;  
#if DOF_ADVANCED_BOKEH_EFFECTS != 0
    alpha *= spherical_abberation(0, ring_count, -BOKEH_SPHERICAL_ABB);    
#endif
    sum_fg  += float4(tap.rgb, 1) * alpha * intersect * fg_weight * is_foreground;
    sum_bg  += float4(tap.rgb, 1) * alpha * intersect * bg_weight * is_foreground;
    sum_all += float4(tap.rgb, 1) * alpha; // * !is_foreground;  

    max_foreground_coc = max(max_foreground_coc, -tap_coc * intersect);   

    float num_samples = density_scale * VERTEX_COUNT * ring_count * (ring_count + 1) / 2 + 1; //+1 -> center

    if(sum_fg.w != 0)  sum_fg.rgb  /= sum_fg.w;
    if(sum_bg.w != 0)  sum_bg.rgb  /= sum_bg.w;
    if(sum_all.w != 0) sum_all.rgb  /= sum_all.w;

    float covered_area = kernel_radius * (ring_count + 0.5) / ring_count;
    //float foreground_opacity = saturate((sum_bg.w == 0 ? 1 : 0) + 1.0/num_samples / sample_alpha(covered_area) * sum_fg.w);    
    float foreground_opacity = saturate(saturate(1 - sum_bg.w * num_samples) + 1.0/num_samples / sample_alpha(covered_area) * sum_fg.w);
    float4 blurry_foreground = lerp(sum_bg, sum_fg, foreground_opacity);

    float foreground_coc_radius = saturate(-tap_coc * BUFFER_WIDTH / LAYER_PIXEL_SIZE_SCALE);

    float foreground_alpha = saturate((sum_fg.w + sum_bg.w) / sample_alpha(covered_area) / num_samples); //ratio of accumulated intersected alphas with alpha of kernel
    blurry_foreground = lerp(blurry_foreground, sum_all, saturate(saturate(1 - foreground_alpha) * foreground_coc_radius));
    
    foreground_alpha = max(foreground_alpha, saturate(-tap_coc * BUFFER_WIDTH / LAYER_PIXEL_SIZE_SCALE)); //if center pixel is in fg, then the fg layer shall be taken
    foreground_alpha *= saturate(max_foreground_coc * BUFFER_WIDTH * 0.125); //dynamic fadeout to fullres

    blurry_foreground = lerp(blurry_foreground, orig, (sum_fg.w + sum_bg.w) < 1e-6); //fig black border bug

    o = blurry_foreground;
    o.w = foreground_alpha;
}

void MergePS(in VSOUT i, out float4 o : SV_Target0)
{
    float4 orig = tex2D(sColorAndDepthTex, i.uv);
    float4 fg = tex2D(sForegroundTex, i.uv);
    float4 bg = tex2D(sBackgroundTex, i.uv);

    float highres_coc = get_coc(i, orig.w);
   
    fg = 0;
    bg = 0;
    float wsum = 0;

    float min_coc = abs(highres_coc);

    [unroll]for(int x = -1; x <= 1; x++)
    [unroll]for(int y = -1; y <= 1; y++)
    {
        float2 offs = float2(x, y) * BUFFER_PIXEL_SIZE * LAYER_PIXEL_SIZE_SCALE;
        float lowres_coc = tex2D(sCOCTexLo, i.uv + offs).x;
        float w = saturate(1e-6 + 0.5 * sqrt(abs(lowres_coc*highres_coc)) * BUFFER_WIDTH); 
        fg += tex2D(sForegroundTex, i.uv + offs) * w;
        bg += tex2D(sBackgroundTex, i.uv + offs) * w;
        wsum += w;
        min_coc = min(min_coc, abs(lowres_coc));
    }

    fg /= wsum;
    bg /= wsum;  

    orig.rgb = undo_premultiply_coc(orig.rgb, highres_coc);

    float2 transition_fgbg = saturate(float2(-highres_coc, highres_coc) * BUFFER_WIDTH / LAYER_PIXEL_SIZE_SCALE);
    transition_fgbg.x = max(fg.w, transition_fgbg.x); //fixes some artifacts 

    o = lerp(orig, bg, transition_fgbg.y);      
    o = lerp(o, fg, transition_fgbg.x);

    pack_hdr(o.rgb); 
    o.w = saturate(max(transition_fgbg.x, saturate(min_coc * BUFFER_WIDTH * 0.25)));
}

void PostPS(in VSOUT i, out float4 o : SV_Target0)
{
    o = tex2D(ColorInput, i.uv); 

    [branch]if(abs(BOKEH_SMOOTHNESS) > 1e-3)
    {
        float ww = o.w;
        float4 maxfilter = float4(o.rgb * o.rgb, 1);
        float3 mintap = 10000; 
        float3 maxtap = 0;
        [loop]for(int r = 1; r <= 3; r++)
        [loop]for(int s = 0; s < r * 4; s++)
        {
            float radi = r / 3.0;
            float2 dir; sincos(s * rcp(r * 4.0) * PI * 2.0, dir.y, dir.x);
            dir *= BUFFER_PIXEL_SIZE * ww;
            dir *= abs(BOKEH_SMOOTHNESS) * 4.0;
            dir *= radi;
            float4 tap = tex2Dlod(ColorInput, i.uv + dir, 0); 
            float tapw = tap.w >= radi; //similar to intersect, helps to keep infocus sharp and bleeding free
            //tapw *= BOKEH_SMOOTHNESS < 0 ? cos(r / 4.0 * 1.57) : 1;
            maxfilter +=float4(tap.rgb * tap.rgb, 1) * tapw;

            mintap = lerp(mintap, min(mintap, tap.rgb), tapw);
            maxtap = lerp(maxtap, max(maxtap, tap.rgb), tapw);
        }
        maxfilter.rgb /= maxfilter.w;
        maxfilter.rgb = sqrt(maxfilter.rgb);

        [branch]
        if(BOKEH_SMOOTHNESS < 0)
        {
            //sharpen mode
            maxfilter.rgb = lerp(o.rgb, maxfilter.rgb, -1.415);
            maxfilter.rgb = lerp(mintap,        maxfilter.rgb, smoothstep(mintap,        maxfilter.rgb, o.rgb));
            maxfilter.rgb = lerp(maxfilter.rgb, maxtap,        smoothstep(maxfilter.rgb, maxtap,        o.rgb));
        }
    
        o.rgb = maxfilter.rgb; 
    }
/*
    [branch]if(USE_FOCUS_HELPER)
    {
        float4 focus_aabb = get_af_aabb();
        float2 aabb_span = focus_aabb.zw - focus_aabb.xy;

        float z = Depth::get_linear_depth(i.uv);  
        float coc = get_coc(i, z); 

        if(abs(coc * BUFFER_WIDTH) > 1.0) o.rg *= coc.xx > 0 ? float2(0.6, 1) : float2(1, 0.8);
        o.rgb = abs(coc * BUFFER_WIDTH) < 0.05 ? 1 : o.rgb;

        float2 normuv = linearstep(focus_aabb.xy, focus_aabb.zw, i.uv);

        if(all(saturate(normuv - normuv * normuv)))
            o.rgb *= 0.8;    
    }*/
}

/*

texture2D ColorAndAlphaTex 			{ Width = BUFFER_WIDTH;   Height = BUFFER_HEIGHT;   Format = RGBA16F;};
sampler2D sColorAndAlphaTex			{ Texture = ColorAndAlphaTex; AddressU = MIRROR; AddressV = MIRROR; };

void StoreAlphaPS(in VSOUT i, out float4 o : SV_Target0)
{
    //First determine own alpha
    float4 orig = tex2D(sColorAndDepthTex, i.uv);
    float coc  = get_coc(i, orig.w); 
    orig.rgb = undo_premultiply_coc(orig.rgb, coc);
    float coc_in_pixels = abs(coc) * BUFFER_WIDTH;
    float covered_area = max(tempF1.w, coc_in_pixels*coc_in_pixels*PI);
    float alpha = rcp(covered_area);

    //now, sample neighbourhood

    float overlapping_alpha = 0;
    float num_intersecting = 0;

    //float kernel_radius = COC_CLAMP;
    //int ring_count = RING_COUNT_MAX;
    int density_scale = max(1, 6 - VERTEX_COUNT);

    BokehKernelData BokehKernel = init_kernel(i.uv); 
    TileData       Tile         = init_tile(i);

    float scatter_radius_max = abs(Tile.min_coc);
    float scatter_radius_min = min(abs(Tile.max_coc), abs(Tile.min_coc)); //technically only max coc but the presence of some super big background coc might ruin this    

    float scatter_radius_highestpossible = get_max_abs_coc(i).x;
    uint ring_count = ceil(scatter_radius_max / scatter_radius_highestpossible * RING_COUNT_MAX);
    float kernel_radius = float(ring_count) / RING_COUNT_MAX * scatter_radius_highestpossible*1.1;  
    ring_count = max(ring_count, 3);

    [branch]
    if(USE_UNDERSAMPLE_PROTECTION)
        ring_count = min(25, ceil(RING_COUNT_MAX * abs(scatter_radius_max) / max(scatter_radius_min, 0.25 * scatter_radius_max)));


    float center_depth = orig.w;


    for(int v = 0; v < VERTEX_COUNT; v++)
    {
        for(float r = 1; r <= ring_count; r++)
        {
            for(float s = 0; s < r * density_scale; s++)
            {                
                //aperture roundness
                float h = s / (r * density_scale);
                float b = tan(PI * 2 / VERTEX_COUNT * (h - 0.5));            
                float g = b * (1.0 + BokehKernel.vertexmat.x) / BokehKernel.vertexmat.z * 0.5 + 0.5;
                h = lerp(h, g, APERTURE_ROUNDNESS);

                float2 tap_location = lerp(BokehKernel.vertex_curr, BokehKernel.vertex_next, h);
                tap_location *= (1.0 - APERTURE_ROUNDNESS) + rsqrt(dot(tap_location, tap_location)) * APERTURE_ROUNDNESS; 
                float ring_radius = (kernel_radius * r) / (ring_count + 0.5);

                float4 tap = tex2Dlod(sColorAndDepthTex, i.uv - tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0);
                float tap_coc  = get_coc(i, tap.w);     
                float tap_coc_in_pixels = abs(tap_coc) * BUFFER_WIDTH;
                float tap_covered_area = max(tempF1.w, tap_coc_in_pixels*tap_coc_in_pixels*PI);
                float tap_alpha = rcp(tap_covered_area);

                float intersecting = sample_intersect(tap_coc, ring_count, r, kernel_radius); 
                float can_overlap = smoothstep(center_depth, center_depth - 0.015, tap.w);//smoothstep(coc, coc - COC_CLAMP * 0.1, tap_coc);

                overlapping_alpha += can_overlap * intersecting * tap_alpha;   //breaking change here!!!!!!!!!!               
            }
        }        
        BokehKernel.vertex_curr = BokehKernel.vertex_next;
        BokehKernel.vertex_next = Math::rotate_2D(BokehKernel.vertex_curr, BokehKernel.vertexmat);
    } 

    float num_samples = density_scale * VERTEX_COUNT * ring_count * (ring_count + 1) / 2 + 1; //+1 -> center
    //overlapping_alpha /= num_samples; //-1 cuz we don't sample center?

    float sample_radius = kernel_radius * (ring_count + 0.5) / ring_count;
    float sample_radius_pixels = sample_radius * BUFFER_SCREEN_SIZE.y;

    float num_covered_pixels = sample_radius_pixels*sample_radius_pixels*PI;
    float undersample_amt = num_covered_pixels / num_samples;
    overlapping_alpha *= undersample_amt; //NO!!! breaking change yes though

    overlapping_alpha *= tempF1.x;

    float4 obscured_pixel;
    obscured_pixel.rgb = orig.rgb;
    obscured_pixel.w = alpha * saturate(1 - overlapping_alpha);
    o = obscured_pixel;
}

void ResolvePS(in VSOUT i, out float4 o : SV_Target0)
{
    float4 orig = tex2D(sColorAndDepthTex, i.uv);
    orig.rgb = undo_premultiply_coc(orig.rgb, get_coc(i, orig.w));

    float coc = get_coc(i, orig.w); 

    float center_obscured_pct = tex2D(sColorAndAlphaTex, i.uv).w;
    float4 blursum = 0;
    float4 holefill = 0;

   // float kernel_radius = COC_CLAMP;
    //int ring_count = RING_COUNT_MAX;
    int density_scale = max(1, 6 - VERTEX_COUNT);

    BokehKernelData BokehKernel = init_kernel(i.uv); 
    TileData       Tile         = init_tile(i);

    float scatter_radius_max = abs(Tile.min_coc);
    float scatter_radius_min = min(abs(Tile.max_coc), abs(Tile.min_coc)); //technically only max coc but the presence of some super big background coc might ruin this    

    float scatter_radius_highestpossible = get_max_abs_coc(i).x;
    uint ring_count = ceil(scatter_radius_max / scatter_radius_highestpossible * RING_COUNT_MAX);
    float kernel_radius = float(ring_count) / RING_COUNT_MAX * scatter_radius_highestpossible*1.1;  
    ring_count = max(ring_count, 3);

    [branch]
    if(USE_UNDERSAMPLE_PROTECTION)
        ring_count = min(25, ceil(RING_COUNT_MAX * abs(scatter_radius_max) / max(scatter_radius_min, 0.25 * scatter_radius_max)));   

    ring_count = RING_COUNT_MAX; 
    kernel_radius = COC_CLAMP;


    float num_samples = density_scale * VERTEX_COUNT * ring_count * (ring_count + 1) / 2 + 1; //+1 -> center
    float sample_radius = kernel_radius * (ring_count + 0.5 + tempF3.x) / ring_count;
    float sample_radius_pixels = sample_radius * BUFFER_SCREEN_SIZE.x;
    float num_covered_pixels = sample_radius_pixels*sample_radius_pixels*PI;
    float undersample_amt = num_covered_pixels / num_samples;

    blursum += float4(orig.rgb, 1) * center_obscured_pct / undersample_amt; //we hit center always, it has a higher probability than it should so reduce


    for(int v = 0; v < VERTEX_COUNT; v++)
    {
        for(float r = 1; r <= ring_count; r++)
        {
            for(float s = 0; s < r * density_scale; s++)
            {                
                //aperture roundness
                float h = s / (r * density_scale);
                float b = tan(PI * 2 / VERTEX_COUNT * (h - 0.5));            
                float g = b * (1.0 + BokehKernel.vertexmat.x) / BokehKernel.vertexmat.z * 0.5 + 0.5;
                h = lerp(h, g, APERTURE_ROUNDNESS);

                float2 tap_location = lerp(BokehKernel.vertex_curr, BokehKernel.vertex_next, h);
                tap_location *= (1.0 - APERTURE_ROUNDNESS) + rsqrt(dot(tap_location, tap_location)) * APERTURE_ROUNDNESS; 
                float ring_radius = (kernel_radius * r) / (ring_count + 0.5);

                float4 tap = tex2Dlod(sColorAndAlphaTex, i.uv - tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0);
                float tap_coc = get_coc(i, tex2Dlod(sColorAndDepthTex, i.uv - tap_location * ring_radius * BUFFER_ASPECT_RATIO, 0).w);     

                float intersecting = sample_intersect(tap_coc, ring_count, r, kernel_radius); 
                float tap_obscured_percent = tap.w; 

                blursum += float4(tap.rgb, 1) * intersecting * tap_obscured_percent; 
                holefill += float4(tap.rgb, 1) * (1-intersecting) * smoothstep(coc, coc + COC_CLAMP * tempF1.z, tap_coc);
           }
        }        
        BokehKernel.vertex_curr = BokehKernel.vertex_next;
        BokehKernel.vertex_next = Math::rotate_2D(BokehKernel.vertex_curr, BokehKernel.vertexmat);
    }

    blursum.rgb /= blursum.w + 1e-8;
    holefill.rgb /= holefill.w + 1e-7;
    o = blursum;
  
  
    blursum.w *= undersample_amt;
    blursum.w *= tempF1.y;
    //blursum.w *= max(tempF1.w, rcp(sample_radius*BUFFER_WIDTH*sample_radius*BUFFER_WIDTH*PI));

    o.rgb = lerp(o.rgb, holefill.rgb, saturate(1 - blursum.w) * saturate(-coc * BUFFER_SCREEN_SIZE.x*0.5));

    pack_hdr(o.rgb);
}
*/





/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_DOF
<
    ui_label = "iMMERSE Pro: Depth of Field";
    ui_tooltip =        
        "                            MartysMods - Depth of Field                           \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "A highly advanced, physically based depth of field effect that accurately simulates\n"
        "the out-of-focus blurring of objects in real cameras.                              \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n";
>
{    
    pass
	{
		VertexShader = SaveMouseVS;
		PixelShader = SaveMousePS;
		RenderTarget = LastMousePt;
		PrimitiveTopology = POINTLIST;
		VertexCount = 1;
    }    
    pass
	{
		VertexShader = FocusVS;
		PixelShader  = FocusReduce16PS;
        RenderTarget = FocusTex16;
    } 
    pass
	{
		VertexShader = FocusVS;
		PixelShader  = FocusReduce1PS;
        RenderTarget = FocusTex1;
        BlendEnable = true;
        SrcBlend = SRCALPHA;
        DestBlend = INVSRCALPHA;
    } 
    pass
	{
		VertexShader = MainVS;
		PixelShader  = MakeInputsPS;
        RenderTarget = ColorAndDepthTex;
    }
    pass
	{
		VertexShader = MainVS;
		PixelShader  = DownsamplePS;
        RenderTarget0 = ColorAndCOCTex;
        RenderTarget1 = COCTexLo;
	}   
    pass
	{
		VertexShader = MainVS;
		PixelShader  = ExtractProminentBokehShapesPS;
        RenderTarget = ProminentBokehTex;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader  = SubtractShapesFromInputPS;
        RenderTarget = ColorAndCOCTex;
        BlendEnable = true;
        BlendOp = REVSUBTRACT;
        SrcBlend = ONE; 
        DestBlend = ONE;
        SrcBlendAlpha = ZERO; //keep CoC in alpha untouched
        DestBlendAlpha = ONE;
	}   
    pass
	{
		VertexShader = MainVS;
		PixelShader  = TileCoCPS;
        RenderTarget = TileCoC;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader  = TileDilatePS;
        RenderTarget = DilatedTileCoC;
	}    
    pass
	{
		VertexShader = MainVS;
		PixelShader  = BokehForegroundPS;
        RenderTarget = ForegroundTex;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader  = BokehBackgroundPS;
        RenderTarget = BackgroundTex;
	} 
    pass
	{
		VertexShader = ScatterVS;
		PixelShader = ScatterPS;		
		PrimitiveTopology = TRIANGLELIST;
		VertexCount = 3 * BUFFER_SCREEN_SIZE.x * BUFFER_SCREEN_SIZE.y / (LAYER_PIXEL_SIZE_SCALE*LAYER_PIXEL_SIZE_SCALE);
		BlendEnable = true;	
        BlendOp = ADD;	
        SrcBlend = ONE; 
		DestBlend = ONE;
        SrcBlendAlpha = ZERO; 
		DestBlendAlpha = ONE;
        RenderTarget0 = BackgroundTex;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader  = MergePS;
	} 
    pass
	{
		VertexShader = MainVS;
		PixelShader  = PostPS;
	}  
    
       
    
    
    /*
    pass
	{
		VertexShader = MainVS;
		PixelShader  = StoreAlphaPS;
        RenderTarget = ColorAndAlphaTex;
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader  = ResolvePS;
	} */
}