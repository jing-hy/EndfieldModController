/*=============================================================================

	ReShade 4 effect file
    github.com/martymcmodding

    Copyright (c) Pascal Gilcher. All rights reserved.

	Support me:
   		paypal.me/mcflypg
   		patreon.com/mcflypg

    Insight 0.1

    changelog:

    0.1:    - initial release    
    0.2:    - disable in screenshots automatically
            - fix a bug on DX12
            
    * Unauthorized copying of this file, via any medium is strictly prohibited
 	* Proprietary and confidential

=============================================================================*/

/*=============================================================================
	Preprocessor settings
=============================================================================*/

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform bool UIENABLE <
    ui_label = "Hide overlays when ReShade menu is closed";
    ui_category = "Global";
> = true;

uniform int CLIPPING_MODE <
	ui_type = "combo";
    ui_label = "Color Clipping Overlay";
	ui_items = "Disabled\0Black/White Clipping\0RGB Clipping\0";
    ui_category = "Color";    
> = 0;

#define CLIPPING_BW  1
#define CLIPPING_RGB 2

uniform int HISTOGRAM_MODE <
	ui_type = "combo";
    ui_label = "Histogram Mode";
	ui_items = "Disabled\0Luminance Histogram\0RGB Histogram\0Luminance Waveform (DX11+ and OpenGL only)\0RGB Waveform (DX11+ and OpenGL only)\0RGB Waveform Parade (DX11+ and OpenGL only)\0";
    ui_category = "Color";
> = 1;

#define HISTO_LUM                   1
#define HISTO_RGB                   2
#define HISTO_WAVEFORM_LUM          3
#define HISTO_WAVEFORM_RGB          4
#define HISTO_WAVEFORM_RGB_PARADE   5

uniform bool SCOPE_COMPACT <
    ui_label = "Compact Mode";
    ui_category = "Color";
> = false;

uniform int INSPECTOR_TYPE <
	ui_type = "combo";
    ui_label = "Inspector Type";
	ui_items = "Disabled\0RGB\0Magnifying Glass\0FFT (DX11+ and OpenGL only)\0";
    ui_category = "Inspector";
> = 0;

#define INSPECTOR_TYPE_RGB 1
#define INSPECTOR_TYPE_MAG 2
#define INSPECTOR_TYPE_FFT 3

uniform float INSPECTOR_SIZE <
    ui_type = "drag";
    ui_min = 0.0;
    ui_max = 3.0;
    ui_label = "Inspector Size";
    ui_category = "Inspector";
> = 0.5;

uniform bool INSPECTOR_POINTANDCLICK <
    ui_label = "Use Point and Click (MMB)";
    ui_category = "Inspector";
> = false;

uniform bool INSPECTOR_BICUBIC <
    ui_label = "Magnifier uses Bicubic Interpolation";
    ui_category = "Inspector";
> = false;

uniform int INSPECTOR_MAG <
    ui_type = "slider";
    ui_min = 4;
    ui_max = 32;
    ui_label = "Inspector Magnification";
    ui_category = "Inspector";
> = 6;

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

uniform float FRAMETIME < source = "frametime";  >;
uniform uint FRAMECOUNT  < source = "framecount"; >;
uniform bool OVERLAY_OPEN < source = "overlay_open"; >;
uniform float2 MOUSE_POINT < source = "mousepoint"; >;

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_math.fxh" 
#include ".\MartysMods\mmx_colorspaces.fxh"
 
//2^n
#define SIZE_SCALE		            LOG2(BUFFER_WIDTH / 1024) //ensures roughly constant cost with super big screen sizes. For big input buffers, this skips pixels
#define HISTORY_SCALE	            3
#define INTERNAL_LUT_SIZE           33

texture ColorInputTex : COLOR;
sampler ColorInput 	{ Texture = ColorInputTex; MinFilter=POINT; MipFilter=POINT; MagFilter=POINT; };

texture2D LastMousePt			    { Width = 1;   Height = 1;                Format = RG16F;  	};
sampler2D sLastMousePt			    { Texture = LastMousePt;  };

#if _COMPUTE_SUPPORTED

#define GRP_SIZE_X          1
#define GRP_SIZE_Y          1024
#define NUM_PIXELS_X        4
#define WARP_SIZE           32
#define NUM_HISTOGRAMS      (GRP_SIZE_Y / WARP_SIZE)

#if BUFFER_WIDTH <= 4096
 #define NUM_COLUMNS_X       CEIL_DIV(BUFFER_WIDTH, NUM_PIXELS_X) 
#else 
 #define NUM_COLUMNS_X       CEIL_DIV(4096, NUM_PIXELS_X)
#endif

texture2D HistogramTexRGBI			    { Width = 256;   Height = 1;                Format = RGBA32F;  	};
sampler2D sHistogramTexRGBI			    { Texture = HistogramTexRGBI;  };
storage stHistogramTexRGBI              { Texture = HistogramTexRGBI; };
texture WaveformTex                     { Width = NUM_COLUMNS_X; Height = 256; Format = RGBA32F; };
sampler sWaveformTex                    { Texture = WaveformTex;};
storage stWaveformTex                   { Texture = WaveformTex; };

#define FFT_WINDOW_SIZE 256

texture FFTInspectMaskRaw { Width = FFT_WINDOW_SIZE; Height = FFT_WINDOW_SIZE; Format = RG32F; MipLevels = LOG2(FFT_WINDOW_SIZE); }; 
sampler sFFTInspectMaskRaw { Texture = FFTInspectMaskRaw;  };

texture FFTInspectMask { Width = FFT_WINDOW_SIZE; Height = FFT_WINDOW_SIZE; Format = RG32F;  }; 
sampler sFFTInspectMask { Texture = FFTInspectMask;  AddressU = WRAP; AddressV = WRAP;};
storage stFFTInspectMask { Texture = FFTInspectMask; };

texture FFTInspectMask2 { Width = FFT_WINDOW_SIZE; Height = FFT_WINDOW_SIZE; Format = RG32F;  }; 
sampler sFFTInspectMask2 { Texture = FFTInspectMask2;  };
storage stFFTInspectMask2 { Texture = FFTInspectMask2; };

#else 

#define HISTORY_SIZE			    ((1 << HISTORY_SCALE) * (1 << HISTORY_SCALE))
#define THREAD_CONFLICT_RES_SIZE    64

texture2D HistogramTexRGBIRaw		    { Width = 256;   Height = THREAD_CONFLICT_RES_SIZE;               Format = RGBA32F;  	};
texture2D HistogramHistoryTexRGBI	    { Width = 256;   Height = HISTORY_SIZE;     Format = RGBA32F;  	};
sampler2D sHistogramTexRGBIRaw			{ Texture = HistogramTexRGBIRaw;  };
sampler2D sHistogramHistoryTexRGBI 	    { Texture = HistogramHistoryTexRGBI; };
texture2D HistogramTexRGBI			    { Width = 256;   Height = 1;                Format = RGBA32F;  	};
sampler2D sHistogramTexRGBI			    { Texture = HistogramTexRGBI;  };

#endif

sampler ColorInputLinear 	{ Texture = ColorInputTex; };


struct VSOUT
{
	float4 vpos : SV_Position;
    float2 uv : TEXCOORD0; 
};

struct CSIN 
{
    uint3 groupthreadid     : SV_GroupThreadID;         //XYZ idx of thread inside group
    uint3 groupid           : SV_GroupID;               //XYZ idx of group inside dispatch
    uint3 dispatchthreadid  : SV_DispatchThreadID;      //XYZ idx of thread inside dispatch
    uint threadid           : SV_GroupIndex;            //flattened idx of thread inside group
};

/*=============================================================================
	Functions
=============================================================================*/

float4 bicubic_catmullrom(in sampler tex, in float2 uv, in float2 texsize)
{
    float2 UV =  uv * texsize;
    float2 tc = floor(UV - 0.5) + 0.5;
	float2 f = UV - tc;
	float2 f2 = f * f; 
	float2 f3 = f2 * f;
    
    float2 w0 = f2 - 0.5 * (f3 + f);
	float2 w1 = 1.5 * f3 - 2.5 * f2 + 1.0;
	float2 w3 = 0.5 * (f3 - f2);
	float2 w12 = 1.0 - w0 - w3;

    float4 ws[3];    
    ws[0].xy = w0;
	ws[1].xy = w12;
	ws[2].xy = w3;

	ws[0].zw = tc - 1.0;
	ws[1].zw = tc + 1.0 - w1 / w12;
	ws[2].zw = tc + 2.0;

	ws[0].zw /= texsize;
	ws[1].zw /= texsize;
	ws[2].zw /= texsize;

    float4 ret;
    ret  = tex2Dlod(tex, float2(ws[1].z, ws[0].w), 0) * ws[1].x * ws[0].y;    
    ret += tex2Dlod(tex, float2(ws[0].z, ws[1].w), 0) * ws[0].x * ws[1].y;    
    ret += tex2Dlod(tex, float2(ws[1].z, ws[1].w), 0) * ws[1].x * ws[1].y;    
    ret += tex2Dlod(tex, float2(ws[2].z, ws[1].w), 0) * ws[2].x * ws[1].y;    
    ret += tex2Dlod(tex, float2(ws[1].z, ws[2].w), 0) * ws[1].x * ws[2].y;    
    float normfact = 1.0 / (1.0 - (f.x - f2.x)*(f.y - f2.y) * 0.25); //PG23: closed form for the weight sum
    return max(0, ret * normfact);   
}

/*=============================================================================
	Shader Entry Points - Scopes
=============================================================================*/

#if _COMPUTE_SUPPORTED

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

    tex2Dstore(stWaveformTex, uint2(i.groupid.x, i.threadid), float4(sum) / (NUM_HISTOGRAMS * NUM_PIXELS_X * min(BUFFER_HEIGHT, 2048)));
}

groupshared float4 binsum[256];

void HistogenCS(in CSIN i)
{    
    uint num_columns = tex2Dsize(sWaveformTex).x;

    float4 bin = 0;
    for(uint c = i.threadid; c < num_columns; c += 256)
        bin += tex2Dfetch(sWaveformTex, uint2(c, i.groupid.x), 0);

    binsum[i.threadid] = bin;
    barrier();

    [loop]
    for(uint stride = 256 / 4; stride > 0; stride >>= 2)
    {
        if(i.threadid < stride)
            binsum[i.threadid] += binsum[i.threadid + stride] + binsum[i.threadid + stride * 2] + binsum[i.threadid + stride * 3];
        barrier();
    }

    if(i.threadid == 0)
        tex2Dstore(stHistogramTexRGBI, uint2(i.dispatchthreadid.x, 0), binsum[0] / num_columns * 16.0);
}


void WriteMaskPS(in VSOUT i, out PSOUT2 o)
{ 
    float2 mousept = int2(tex2Dfetch(sLastMousePt, int2(0, 0)).xy);
    float3 color = tex2Dfetch(ColorInput, int2(i.vpos.xy - FFT_WINDOW_SIZE/2 + mousept)).rgb;
    color /= 1.01 - color;
    o.t0.x = dot(0.333, color);
 
    o.t0.yzw = 0;
    o.t1 = o.t0;
     
}

#define FFT_WORKING_SIZE        FFT_WINDOW_SIZE
#define FFT_RADIX               2
#define FFT_INSTANCE            FFTPassX 
#define FFT_AXIS                0 //X
#define FFT_CHANNELS            2

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassXCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sFFTInspectMask, stFFTInspectMask2, true);}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

#define FFT_WORKING_SIZE        FFT_WINDOW_SIZE
#define FFT_RADIX               2
#define FFT_INSTANCE            FFTPassY
#define FFT_AXIS                1 //Y
#define FFT_CHANNELS            2

#include ".\MartysMods\mmx_fft.fxh"
void FourierPassYCS(in CSIN i){FFT_INSTANCE::FFTPass(i.dispatchthreadid.xy, i.threadid, sFFTInspectMask2, stFFTInspectMask, true);}

#undef FFT_WORKING_SIZE
#undef FFT_RADIX
#undef FFT_INSTANCE 
#undef FFT_AXIS 
#undef FFT_CHANNELS

#else

#define GRID_DIM_X				    (BUFFER_WIDTH >> SIZE_SCALE)
#define GRID_DIM_Y				    (BUFFER_HEIGHT >> SIZE_SCALE)
#define SUB_GRID_DIM_X  		    (GRID_DIM_X >> HISTORY_SCALE)
#define SUB_GRID_DIM_Y  		    (GRID_DIM_Y >> HISTORY_SCALE)

struct VSOUTRGBI
{
	float4                  vpos        : SV_Position;
    float2                  uv          : TEXCOORD0;
    nointerpolation uint 	channel		: TEXCOORD1; 
};

//writes single histogram for current frame
VSOUTRGBI HistogramGenRGBIRawVS(in uint vertex_id : SV_VertexID)
{
    VSOUTRGBI o;

    o.channel = vertex_id % 4u;       
    vertex_id /= 4u;                    

    uint rowtowrite = vertex_id % THREAD_CONFLICT_RES_SIZE;     

    [flatten]
    if(!HISTOGRAM_MODE
    || HISTOGRAM_MODE == HISTO_LUM && o.channel != 3 
    || HISTOGRAM_MODE >= HISTO_WAVEFORM_LUM  
    || (UIENABLE && !OVERLAY_OPEN)
    ) rowtowrite = -10000; 

    static const uint grid_subgrid_ratio = 1u << HISTORY_SCALE;
    uint history_num = FRAMECOUNT % HISTORY_SIZE;

    uint2 current_subgrid_point             = uint2(vertex_id % SUB_GRID_DIM_X, vertex_id / SUB_GRID_DIM_X);
    uint2 current_subgrid_to_grid_offset    = uint2(history_num % grid_subgrid_ratio, history_num / grid_subgrid_ratio);
    uint2 current_grid_point = current_subgrid_point * grid_subgrid_ratio + current_subgrid_to_grid_offset;

    static const uint grid_to_pixelraster_ratio = 1u << SIZE_SCALE;
    uint2 current_pixel_point = current_grid_point * grid_to_pixelraster_ratio; 
    current_pixel_point += grid_to_pixelraster_ratio / 2; 

    float4 c = tex2Dfetch(ColorInput, current_pixel_point);
    c.w = dot(c.rgb, float3(0.299, 0.587, 0.114));

    float val = dot(c, int4(0, 1, 2, 3) == o.channel.xxxx);
    //write point for 256x1 texture
    o.uv.x = (round(val * 255) + 0.5) / 256.0;
   	o.uv.y = (0.5 + rowtowrite) / THREAD_CONFLICT_RES_SIZE; 
   	o.vpos = float4(o.uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0); //can use the borked uv, as we're writing points anyways, otherwise define UV regularly and use transformed UV to define vpos
    return o;
}

VSOUT HistogramHistoryVS(in uint id : SV_VertexID)
{
    VSOUT o;    

   	uint history_size = HISTORY_SIZE; 
    uint history_num = FRAMECOUNT % history_size;

    //setup standard triangle for the UV at location
    o.uv.x = (id == 2) ? 2.0 : 0.0;
    o.uv.y = (id == 1) ? 2.0 : 0.0;

    //define area to write to in UV space of target
    float2 target_uv = o.uv;
    //transform to current row
    target_uv.y += history_num;
    target_uv.y /= history_size;
    o.vpos = float4(target_uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return o;
}

void WritePointRGBIPS(in VSOUTRGBI i, out float4 o : SV_Target0)
{
	o = float4(int4(0, 1, 2, 3) == i.channel.xxxx) * rcp(SUB_GRID_DIM_X * SUB_GRID_DIM_Y);
}

void HistogramWriteToHistoryRGBIRawPS(in VSOUT i, out float4 o : SV_Target0)
{
    o = 0;
    for(int j = 0; j < THREAD_CONFLICT_RES_SIZE; j++)
        o += tex2Dlod(sHistogramTexRGBIRaw, float4(i.uv.x, (j + 0.5)/THREAD_CONFLICT_RES_SIZE,0,0));
}

void FlattenHistogramHistoryPS(in VSOUT i, out float4 o : SV_Target0)
{
	o = 0;
    for(float j = 0; j < HISTORY_SIZE / 2; j++)
        o += tex2Dlod(sHistogramHistoryTexRGBI, float2(i.uv.x, (j * 2 + 1) / 64.0), 0);
	o /= HISTORY_SIZE;
}

#endif 

/*=============================================================================
	Shader Entry Points - Visualization
=============================================================================*/

VSOUT ScopeVS(in uint id : SV_VertexID)
{
    float2 wsize = !SCOPE_COMPACT ? float2(0.5, 0.3) : float2(0.3, 0.2);
    if(HISTOGRAM_MODE >= HISTO_WAVEFORM_LUM) wsize.x *= 1.2;
    if(HISTOGRAM_MODE == HISTO_WAVEFORM_RGB_PARADE && !SCOPE_COMPACT) wsize.x *= 1.2;
    float2 woffs = 0.03;

    VSOUT o;    
    o.uv.xy = id.xx == uint2(2, 1) ? 2.0.xx : 0.0.xx;    

    float2 pos = o.uv.xy * wsize + woffs;   

    pos *= BUFFER_ASPECT_RATIO; 
    pos /= max(1.0, BUFFER_ASPECT_RATIO.y);     

    o.vpos = float4(pos * 2.0 - 1.0, 0, 1); 

    if(!HISTOGRAM_MODE || (UIENABLE && !OVERLAY_OPEN)) o.vpos = 1000000;

    return o;
}

void ScopePS(in VSOUT i, out float3 o : SV_Target0)
{
    if(any(saturate(i.uv - 1.0))) discard;

    float3 color_bg       = 0.1;
    float3 color_area     = !SCOPE_COMPACT ? 0.3 : 0.8;
    float3 color_outline  = 0.8;
    float width_outline   = 0.5;

    float3 color_border   = 0.8;
    float  width_border   = !SCOPE_COMPACT ? 4.0 : 0.0;

    float2 pixelsize = abs(float2(ddx(i.uv.x), ddy(i.uv.y)));
    float2 bordersize = pixelsize * width_border;
    float bordermask = any(step(min(i.uv, 1-i.uv), bordersize));

    if(bordermask)
    {
        o = color_border;
        return;
    }

    //resize UV to it fits inside the rectangle minus border
    i.uv = (i.uv - bordersize) / (1 - bordersize * 2);    

    float3 scope = 0;
    float3 deltax = 0;
    switch(HISTOGRAM_MODE)
    {
        case HISTO_LUM: //luma histo
        scope = log(tex2Dlod(sHistogramTexRGBI, i.uv, 0).w + 1) * 100.0;
        if(!SCOPE_COMPACT) deltax = log(tex2Dlod(sHistogramTexRGBI, i.uv + float2(pixelsize.x, 0), 0).w + 1) * 100.0 - log(tex2Dlod(sHistogramTexRGBI, i.uv - float2(pixelsize.x, 0), 0).w + 1) * 100.0;
        break;
        case HISTO_RGB: //rgb histo
        scope = log(tex2Dlod(sHistogramTexRGBI, i.uv, 0).rgb + 1) * 100.0;  
        if(!SCOPE_COMPACT) deltax = log(tex2Dlod(sHistogramTexRGBI, i.uv + float2(pixelsize.x, 0), 0).rgb + 1) * 100.0 - log(tex2Dlod(sHistogramTexRGBI, i.uv - float2(pixelsize.x, 0), 0).rgb + 1) * 100.0; 
        break;
#if _COMPUTE_SUPPORTED
        case HISTO_WAVEFORM_LUM: //luma wavefront
        scope = tex2Dlod(sWaveformTex, i.uv, 0).w;
        break;
        case HISTO_WAVEFORM_RGB: //rgb wavefront
        scope = tex2Dlod(sWaveformTex, i.uv, 0).rgb;
        break;
        case HISTO_WAVEFORM_RGB_PARADE: //rgb wavefront parade
        scope = tex2Dlod(sWaveformTex, float2(frac(i.uv.x * 2.999), i.uv.y), 0).rgb;
        scope *= saturate(uint3(i.uv.xxx * 2.999) == uint3(0,1,2));
        break;
#endif
    }    

    o = 0;

    [branch]
    if(HISTOGRAM_MODE >= HISTO_WAVEFORM_LUM)
    {
        float barsize = 1.04 * pixelsize.y;
        i.uv.y += barsize * 0.5;

        float2 grid = step(frac(i.uv.yy * float2(4.0, 12.0)) / float2(4.0, 12.0), barsize);
        grid   *= step(abs(i.uv.y - 0.5), 0.5 - barsize * 2.0);
        grid.y *= step(0.4, abs(i.uv.y - 0.5));  
        
        o = saturate(scope * 1000.0);
        o = lerp(o, dot(0.333, frac(o + 0.5)), saturate(grid.x + grid.y));
    }
    else 
    {            
        o = scope.xyz > i.uv.yyy ? color_area : color_bg;
        if(!SCOPE_COMPACT) 
        {
            float3 gradlen = sqrt(deltax * deltax + pixelsize.x * pixelsize.x * 4.0);   
            float3 curve = abs(scope - i.uv.yyy)/gradlen <= width_outline;      
            o = curve ? color_outline : o;
        }
    }
}

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv);
    return o;
}

VSOUT MasksVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv);
    o.vpos *= CLIPPING_MODE == 0 ? 0 : 1;
    o.vpos *= !(UIENABLE && !OVERLAY_OPEN);
    return o;
}

void MasksPS(in VSOUT i, out float3 o : SV_Target0)
{    
    float3 col = tex2D(ColorInput, i.uv).rgb;
    float l = dot(col, 0.3333333);

    float3 tcol = col;
    col = CLIPPING_MODE == CLIPPING_BW ? lerp(col, 1 - col, saturate(l - l * l) < 0.003) : col;
    col = CLIPPING_MODE == CLIPPING_RGB ? lerp(col, 1 - col, saturate(tcol - tcol * tcol) < 0.003) : col;  

    o = col;
}

float2 get_mouse_point()
{
    float2 mouse_point_reference = MOUSE_POINT;
    float2 mouse_point_stored = tex2Dfetch(sLastMousePt, 0.0.xx, 0).xy;
    if(INSPECTOR_POINTANDCLICK && any(mouse_point_stored > 0.5))
        mouse_point_reference = mouse_point_stored;

    return mouse_point_reference;
}
//faster than discard because this kills the write in the geometry stage
uniform bool MMB_DOWN < source = "mousebutton"; keycode = 2; mode = ""; >;

float4 SaveMouseVS(in uint id : SV_VertexID) : SV_Position
{    
    return float4(!MMB_DOWN, !MMB_DOWN, 0, 1); 
}

void SaveMousePS(in float4 vpos : SV_Position, out float2 o : SV_Target0)
{ 
    o = MOUSE_POINT;
}

struct VSOUT_DrawDigit
{
	float4                  vpos        : SV_Position;
    float2                  uv          : TEXCOORD0;
    nointerpolation uint    seg         : TEXCOORD3;
    nointerpolation uint    ch          : TEXCOORD4;
};

#define DIGIT_PADDING float2(0.15, 0.1)

VSOUT_DrawDigit DigitDrawVS(in uint id : SV_VertexID)
{
    VSOUT_DrawDigit o;
    o.uv.xy = (id.xx % 3) == uint2(2, 1) ? 2.0.xx : 0.0.xx;   

    float2 mouse_point = get_mouse_point(); 

    uint3 RGBtuple = floor(tex2Dfetch(ColorInput, mouse_point, 0).rgb * 255 + 0.5);

    uint number_id = id / 9;
    uint total_digit_id = id/3;
    uint number_digit_id  = total_digit_id % 3;
    uint curr_val = RGBtuple[number_id];  

    float2 wsize = float2(0.05,0.1) * 0.08 * exp2(INSPECTOR_SIZE) * BUFFER_ASPECT_RATIO;
    wsize *= 1.0 + DIGIT_PADDING * 2;
    float2 woffs = mouse_point * BUFFER_PIXEL_SIZE + 0.01 + float2(wsize.x, 0) * total_digit_id;

    float2 pos = o.uv.xy * wsize + woffs;

    o.vpos = float4(pos * float2(2.0, -2.0) + float2(-1.0, 1.0), 0, 1);
    if(INSPECTOR_TYPE != INSPECTOR_TYPE_RGB || (UIENABLE && !OVERLAY_OPEN)) o.vpos = 0;

    uint curr_digit = 2 - number_digit_id; //read front to back
    uint digit_val = floor(curr_val / round(pow(10, curr_digit))) % 10;

    uint segmentmask[10] = {126,48,109,121,51,91,95,112,127,123};

    o.seg = segmentmask[digit_val];
    o.ch = number_id;
    return o;
}

void DigitDrawPS(in VSOUT_DrawDigit i, out float3 o : SV_Target0)
{      
    if(any(saturate(i.uv - 1.0))) discard; //crop triangle
    i.uv = linearstep(DIGIT_PADDING, 1-DIGIT_PADDING, i.uv); //normalize UV inside padding

    if(saturate(!all(i.uv - i.uv * i.uv))) {o = 0; return;} //set padding to black

    uint2 pixel = floor(i.uv.xy * float2(4.99, 8.99)); 
    pixel.x = ceil((pixel.x - 0.5) * 0.33); //convert 9x5 pixel grid to 5x3
    pixel.y = ceil(sin(pixel.y * 1.5708) * 0.2 + (pixel.y - 0.5) * 0.43);

    uint pixel_to_segment[3 * 5] = {0,1,0,6,0,2,0,7,0,5,0,3,0,4,0};
    uint segmentid = pixel_to_segment[pixel.x + pixel.y * 3];

    //check if the bit for the segment is set
    uint segmentlist = uint(i.seg);
    segmentlist /= exp2(7 - segmentid);
    float islit = segmentlist % 2;

    o = islit * (i.ch == uint3(0,1,2));
}

VSOUT InspectorDrawVS(in uint id : SV_VertexID)
{
    VSOUT o;    
    o.uv.xy = id.xx == uint2(2, 1) ? 2.0.xx : 0.0.xx;

    float2 mouse_point = get_mouse_point(); 

    float2 wsize = 0.06 * exp2(INSPECTOR_SIZE) * BUFFER_ASPECT_RATIO;

#if _COMPUTE_SUPPORTED
    if(INSPECTOR_TYPE == INSPECTOR_TYPE_FFT)
    {
        wsize = FFT_WINDOW_SIZE * BUFFER_PIXEL_SIZE.xy;
    }
#endif
    float2 woffs = mouse_point * BUFFER_PIXEL_SIZE;

    if(INSPECTOR_TYPE == INSPECTOR_TYPE_MAG || INSPECTOR_TYPE == INSPECTOR_TYPE_FFT) woffs -= 0.5 * wsize; //center on mouse point

    float2 pos = o.uv.xy * wsize + woffs;  
    
    o.vpos = float4(pos * float2(2.0, -2.0) + float2(-1.0, 1.0), 0, 1);
    if(INSPECTOR_TYPE == 0 || INSPECTOR_TYPE == INSPECTOR_TYPE_RGB || (UIENABLE && !OVERLAY_OPEN)) o.vpos = 0;

    return o;
}

void InspectorDrawPS(in VSOUT i, out float3 o : SV_Target0)
{ 
    float2 nuv = i.uv * 2 - 1;
    float r = length(nuv);

    o = 0;   

    float2 mouse_point = get_mouse_point();
    
    if(INSPECTOR_TYPE == INSPECTOR_TYPE_MAG)
    {
        float2 cuv = (i.vpos.xy - mouse_point) * BUFFER_PIXEL_SIZE; //i.uv is not screen uv but 0-1 uv inside square overlay
        cuv /= INSPECTOR_MAG; //magnification
        cuv += mouse_point * BUFFER_PIXEL_SIZE;

        o = tex2D(ColorInput, cuv).rgb;

        if(INSPECTOR_BICUBIC)
        {
            o = bicubic_catmullrom(ColorInputLinear, cuv, BUFFER_SCREEN_SIZE).rgb;
        }

        float3 orig = tex2Dfetch(ColorInput, i.vpos.xy).rgb;
        
        o = lerp(orig, o, smoothstep(1.0, 1.0 - 1.0*fwidth(r), r));

        if(r > 1) discard;
    }  
#if _COMPUTE_SUPPORTED
    else if(INSPECTOR_TYPE == INSPECTOR_TYPE_FFT)
    {
        float2 tuv = i.uv;
        if(!Math::inside_screen(tuv)) discard;

        //tuv = frac(tuv + 0.5);
        tuv += 0.5; //wrap mode in texture
        float2 fft = tex2Dlod(sFFTInspectMask, tuv, 0).xy;
        float mag = sqrt(dot(fft.xy, fft.xy));        
        mag /= tex2Dlod(sFFTInspectMaskRaw, 0.5.xx, 7).x;;
        o = log(1 + mag * 2.0);
    }
#endif  
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_INSIGHT_HISTOGRAM
<
    ui_label = "iMMERSE Pro: Insight (generate Histogram)";
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
        ComputeShader = HistogenCS<1, 256>;
    	DispatchSizeX = 256;
    	DispatchSizeY = 1; 
    }
#else 
    pass
	{
		VertexShader = HistogramGenRGBIRawVS;
		PixelShader = WritePointRGBIPS;
		RenderTarget = HistogramTexRGBIRaw;
		PrimitiveTopology = POINTLIST;
		VertexCount = SUB_GRID_DIM_X * SUB_GRID_DIM_Y * 4; //RGBI
		ClearRenderTargets = true; 
		BlendEnable = true; 
		SrcBlend = ONE; 
		DestBlend = ONE;
		SrcBlendAlpha = ONE;
		DestBlendAlpha = ONE;
    }
    pass
	{
		VertexShader = HistogramHistoryVS;
		PixelShader = HistogramWriteToHistoryRGBIRawPS;
		RenderTarget = HistogramHistoryTexRGBI;
		ClearRenderTargets = false; //should be true by default but you never know...
									//set to true to see how each line is written
	}
    pass
	{
		VertexShader = MainVS;
		PixelShader = FlattenHistogramHistoryPS;
		RenderTarget = HistogramTexRGBI;
	}
#endif	
}

technique MartysMods_INSIGHT 
<
    enabled_in_screenshot = false;
    ui_label = "iMMERSE Pro: Insight";
    ui_tooltip =        
        "                            MartysMods - INSIGHT                              \n"
        "                   MartysMods Epic ReShade Effects (iMMERSE)                  \n"
        "______________________________________________________________________________\n"
        "\n"

        "Insight fulfills all your pixel peeper desires. Realtime histogram, magnifying\n"
        "glass or checking the RGB color of a pixel, Insight can do it.                \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                            \n"
        "\n"       
        "______________________________________________________________________________";
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
        VertexShader = MasksVS;
		PixelShader = MasksPS;
    }    
    pass 
    {         
        VertexShader = ScopeVS;
		PixelShader = ScopePS;
    }
    pass 
    {         
        VertexShader = DigitDrawVS;
		PixelShader = DigitDrawPS;
        PrimitiveTopology = TRIANGLELIST;
		VertexCount = 3 * 9;
    }
#if _COMPUTE_SUPPORTED
    pass
	{
		VertexShader = MainVS;
		PixelShader = WriteMaskPS;
		RenderTarget0 = FFTInspectMask;
        RenderTarget1 = FFTInspectMaskRaw;
    }
    pass FFTX          {ComputeShader = FourierPassXCS<FFT_WINDOW_SIZE/2, 1>; DispatchSizeX = 1; DispatchSizeY = FFT_WINDOW_SIZE; }
    pass FFTY          {ComputeShader = FourierPassYCS<1, FFT_WINDOW_SIZE/2>; DispatchSizeX = FFT_WINDOW_SIZE; DispatchSizeY = 1; }
#endif
    pass 
    {         
        VertexShader = InspectorDrawVS;
		PixelShader = InspectorDrawPS;
    }
}
