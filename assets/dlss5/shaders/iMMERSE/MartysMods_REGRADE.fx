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

    ReGrade 0.13

    Author:         Pascal Gilcher

    More info:      https://martysmods.com
                    https://patreon.com/mcflypg
                    https://github.com/martymcmodding 

    changelog:

    0.1:    - initial release
    0.2:    - ported to refactored qUINT structure
            - removed RGB split from tone curve and lift gamma gain, replaced with
              with RGB selector
            - fixed bug with color remapper red affecting pure white
            - add more grading controls
            - remade lift gamma gain to fit convention
            - replaced histogram with McFly's '21 bomb ass histogram (TM)
            - added split toning
            - switched to internal LUT processing
    0.3:    - switched to LUT atlas for free arrangement of CC operations
            - added clipping mask
            - fixed bug with levels
            - closed UI sections by default
            - added vignette
            - improved color remap - still allows all hues, but now allows raising saturation
    0.4:    - changed LUT sampling to tetrahedral
            - flattened LUTs, improves performance greatly
    0.5:    - added color balance node
            - added dark wash feature
            - extended levels to in/out
            - added gamma to adjustments
    0.6:    - remade histogram UI
            - added dithering
    0.7:    - added compute histogram
            - integration with SOLARIS
            - remade hue controls entirely
            - added waveform mode for compute enabled platforms
            - fixed colorspace linear conversion in xyz, lab and oklab
            - remade split toning
            - moved waveform to Insight
    0.8:    - remade color balance 
            - added special transforms 
            - remade tone curve 
    0.9:    - update LUTs only when GUI is active or LUTs are empty
            - change LUT size for least perceptual error at a given quality
            - optimize tetrahedral sampling
    0.10:   - added filmic gamma
            - vast optimizations for SOLARIS
            - better depth mask for SOLARIS
            - different blend modes for SOLARIS
    0.11:   - added HSV lut indexing to improve greyscale gradients
            - added dequantize
            - remade split tone for better blending and saturation based toning
            - modified color remapper to use smoothstepped ranges instead
            - extended lift gamma gain with Resolve's formula
            - improved saturation and vibrance in adjustments layer
            - added Lab based white balance
    0.12:   - modify HSL tools to protect greys, change L to gamma
            - add trilinear sampling
            - add native color processing option
            - rename white balance to calibration and add primary adjustments
            - major cleanup
    0.12.1  - fix for ReShade 5.6
    0.13    - port to iMMERSE format
            - fix bug with color remapper
            - remove native color processing
            - add compute path for LUT building
            - major refactor for future proofing code

=============================================================================*/

/*=============================================================================
	Preprocessor settings
=============================================================================*/

#ifndef ENABLE_SOLARIS_REGRADE_PARITY
 #define ENABLE_SOLARIS_REGRADE_PARITY                 0   //[0 or 1]      If enabled, ReGrade takes HDR input from SOLARIS as color buffer instead. This allows HDR exposure, bloom and color grading to work nondestructively
#endif

/*=============================================================================
	UI Uniforms
=============================================================================*/

uniform int UIHELP <
	ui_type = "radio";
	ui_label = " ";	
	ui_text = "How to use ReGrade:\n\n"
    "ReGrade is a modular color grading platform.\n"
    "Pick any color grading operation in the slots below,\n"
    "then adjust its parameters in the respective section.\n\n"
    "CAUTION: You *can* pick operations multiple times, but they do NOT\n"
    "have separate controls, so it is advised to not use them twice.\n\n"
    "To use the histogram/waveforms, enable the respective\n"
    "technique in the technique window above."
   ;
	ui_category = ">>>> OVERVIEW / HELP (click me) <<<<";
	ui_category_closed = false;
>;

#define LABEL_NONE              "None"
#define LABEL_LEVELS            "Levels"
#define LABEL_ADJ               "Adjustments"
#define LABEL_LGG               "Lift Gamma Gain"
#define LABEL_CALIB             "Calibration"
#define LABEL_REMAP             "Color Remapping"
#define LABEL_TONECURVE         "Tone Curve"
#define LABEL_SPLIT             "Split Toning"
#define LABEL_CB                "Color Balance"
#define LABEL_SPECIAL           "Special Transforms"

#define COMBINE(a, b) a ## b
#define CONCAT(a,b) COMBINE(a, b)
#define SECTION_PREFIX          "Parameters for "

#define SECTION_LEVELS          CONCAT(SECTION_PREFIX, LABEL_LEVELS) 
#define SECTION_ADJ             CONCAT(SECTION_PREFIX, LABEL_ADJ) 
#define SECTION_LGG             CONCAT(SECTION_PREFIX, LABEL_LGG) 
#define SECTION_CALIB           CONCAT(SECTION_PREFIX, LABEL_CALIB) 
#define SECTION_REMAP           CONCAT(SECTION_PREFIX, LABEL_REMAP) 
#define SECTION_TONECURVE       CONCAT(SECTION_PREFIX, LABEL_TONECURVE) 
#define SECTION_SPLIT           CONCAT(SECTION_PREFIX, LABEL_SPLIT) 
#define SECTION_CB              CONCAT(SECTION_PREFIX, LABEL_CB) 
#define SECTION_SPECIAL         CONCAT(SECTION_PREFIX, LABEL_SPECIAL) 

#define GRADE_ID_NONE           0
#define GRADE_ID_LEVELS         1
#define GRADE_ID_ADJ            2
#define GRADE_ID_LGG            3
#define GRADE_ID_CALIB          4
#define GRADE_ID_REMAP          5
#define GRADE_ID_TONECURVE      6
#define GRADE_ID_SPLIT          7
#define GRADE_ID_CB             8
#define GRADE_ID_SPECIAL        9

#define NUM_SECTIONS 9 //cannot use this to generate the nodes below! Increment and extend concat, add node

#define concat_all(a,b,c,d,e,f,g,h,i,j) a ## "\0" ## b ## "\0" ##c ## "\0" ##d ## "\0" ##e ## "\0" ##f ## "\0" ##g ## "\0" ##h ## "\0" ##i ## "\0" ##j ## "\0"  
#define CURR_ITEMS concat_all(LABEL_NONE, LABEL_LEVELS, LABEL_ADJ, LABEL_LGG, LABEL_CALIB, LABEL_REMAP, LABEL_TONECURVE, LABEL_SPLIT, LABEL_CB, LABEL_SPECIAL)

uniform int NODE1 <
	ui_type = "combo";
    ui_label = "Slot 1";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE2 <
	ui_type = "combo";
    ui_label = "Slot 2";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE3 <
	ui_type = "combo";
    ui_label = "Slot 3";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE4 <
	ui_type = "combo";
    ui_label = "Slot 4";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE5 <
	ui_type = "combo";
    ui_label = "Slot 5";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE6 <
	ui_type = "combo";
    ui_label = "Slot 6";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE7 <
	ui_type = "combo";
    ui_label = "Slot 7";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE8 <
	ui_type = "combo";
    ui_label = "Slot 8";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform int NODE9 <
	ui_type = "combo";
    ui_label = "Slot 9";
	ui_items = CURR_ITEMS;
    ui_category = "ORDER OF COLOR OPERATIONS";
> = 0;

uniform bool BYPASS_LEVELS <
    ui_label = CONCAT("Bypass ", LABEL_LEVELS);
    ui_category = SECTION_LEVELS;
    ui_category_closed = true;
> = false;

uniform float INPUT_BLACK_LVL <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 255.0;
	ui_step = 1.0;
	ui_label = "Black Level In";
    ui_category = SECTION_LEVELS;
    ui_category_closed = true;
> = 0.0;

uniform float INPUT_WHITE_LVL <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 255.0;
	ui_step = 1.0;
	ui_label = "White Level In";
    ui_category = SECTION_LEVELS;
    ui_category_closed = true;
> = 255.0;

uniform float OUTPUT_BLACK_LVL <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 255.0;
	ui_step = 1.0;
	ui_label = "Black Level Out";
    ui_category = SECTION_LEVELS;
    ui_category_closed = true;
> = 0.0;

uniform float OUTPUT_WHITE_LVL <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 255.0;
	ui_step = 1.0;
	ui_label = "White Level Out";
    ui_category = SECTION_LEVELS;
    ui_category_closed = true;
> = 255.0;

uniform bool BYPASS_ADJ <
    ui_label = CONCAT("Bypass ", LABEL_ADJ);
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = false;

uniform float GRADE_CONTRAST <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Contrast";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform float GRADE_EXPOSURE <
	ui_type = "drag";
	ui_min = -4.0; ui_max = 4.0;
	ui_label = "Exposure";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform float GRADE_GAMMA <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Gamma";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform float GRADE_FILMIC_GAMMA <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Filmic Gamma";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform float GRADE_SATURATION <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Saturation";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform float GRADE_VIBRANCE <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Vibrance";
    ui_category = SECTION_ADJ;
    ui_category_closed = true;
> = 0.0;

uniform bool BYPASS_LGG <
    ui_label = CONCAT("Bypass ", LABEL_LGG);
    ui_category = SECTION_LGG;
    ui_category_closed = true;
> = false;

uniform int INPUT_LGG_MODE <
	ui_type = "combo";
    ui_label = "Lift Gamma Gain Mode";
	ui_items = " American Society of Cinematographers\0 DaVinci Resolve\0";
    ui_category = SECTION_LGG;
    ui_category_closed = true;  
> = 0;

uniform float3 INPUT_LIFT_COLOR <
  	ui_type = "color";
  	ui_label="Lift";
  	ui_category = SECTION_LGG;
    ui_category_closed = true;    
> = float3(0.5, 0.5, 0.5);

uniform float3 INPUT_GAMMA_COLOR <
  	ui_type = "color";
  	ui_label="Gamma";
  	ui_category = SECTION_LGG;
      ui_category_closed = true;    
> = float3(0.5, 0.5, 0.5);

uniform float3 INPUT_GAIN_COLOR <
  	ui_type = "color";
  	ui_label="Gain";
  	ui_category = SECTION_LGG;
      ui_category_closed = true;    
> = float3(0.5, 0.5, 0.5);

uniform bool BYPASS_CALIB <
    ui_label = CONCAT("Bypass ", LABEL_CALIB);
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = false;

uniform float INPUT_COLOR_TEMPERATURE <
	ui_type = "drag";
	ui_min = 1700.0; ui_max = 40000.0;
    ui_step = 10.0;
	ui_label = "Color Temperature";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = 6500.0;

uniform float INPUT_COLOR_LAB_A <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
    ui_step = 0.01;
	ui_label = "Lab A Offset (Green - Magenta)";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = 0.0;

uniform float INPUT_COLOR_LAB_B <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
    ui_step = 0.01;
	ui_label = "Lab B Offset (Blue - Orange)";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = 0.0;

uniform int INPUT_COLOR_PRIMARY_MODE <
	ui_type = "combo";
    ui_label = "R|G|B Primary Mode";
	ui_items = " ReGrade Legacy\0 Barycentric\0 Hue Based\0";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;  
> = 0;

uniform float3 INPUT_COLOR_PRIMARY_HUE <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
    ui_step = 0.01;
	ui_label = "R|G|B Primary Hue";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = float3(0.0, 0.0, 0.0);

uniform float3 INPUT_COLOR_PRIMARY_SAT <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
    ui_step = 0.01;
	ui_label = "R|G|B Primary Saturation";
    ui_category = SECTION_CALIB;
    ui_category_closed = true;
> = float3(0.0, 0.0, 0.0);

uniform bool BYPASS_REMAP <
    ui_label = CONCAT("Bypass ", LABEL_REMAP);
    ui_category = SECTION_REMAP;
    ui_category_closed = true;
> = false;

uniform float3 COLOR_REMAP_RED <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Red";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;   
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_ORANGE <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Orange";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;    
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_YELLOW <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Yellow";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;     
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_GREEN <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Green";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;   
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_AQUA <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Aqua";
	ui_category = SECTION_REMAP;
    ui_category_closed = true;
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_BLUE <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Blue";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;    
> = float3(0.0, 0.0, 0.0);

uniform float3 COLOR_REMAP_MAGENTA <
  	ui_type = "drag";
    ui_min = -1.0;
    ui_max = 1.0;
  	ui_label="Hue|Sat|Value Magenta";
  	ui_category = SECTION_REMAP;
      ui_category_closed = true;     
> = float3(0.0, 0.0, 0.0);

uniform bool BYPASS_TONECURVE <
    ui_label = CONCAT("Bypass ", LABEL_TONECURVE);
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = false;

uniform float TONECURVE_SHADOWS <
	ui_type = "drag";
	ui_min = -1.00; ui_max = 1.00;
	ui_label = "Shadows";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.00;

uniform float TONECURVE_DARKS <
	ui_type = "drag";
	ui_min = -1.00; ui_max = 1.00;
	ui_label = "Darks";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.00;

uniform float TONECURVE_LIGHTS <
	ui_type = "drag";
	ui_min = -1.00; ui_max = 1.00;
	ui_label = "Lights";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.00;

uniform float TONECURVE_HIGHLIGHTS <
	ui_type = "drag";
	ui_min = -1.00; ui_max = 1.00;
	ui_label = "Highlights";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.00;

uniform float TONECURVE_DARKWASH_RANGE <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Dark Wash Range";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.2;
uniform float TONECURVE_DARKWASH_INT <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Dark Wash Intensity";
    ui_category = SECTION_TONECURVE;
    ui_category_closed = true;
> = 0.0;

uniform bool BYPASS_SPLIT <
    ui_label = CONCAT("Bypass ", LABEL_SPLIT);
    ui_category = SECTION_SPLIT;
    ui_category_closed = true;
> = false;

uniform int SPLITTONE_MODE <
	ui_type = "combo";
    ui_label = "Split Mode";
	ui_items = " Shadows/Highlights\0 Greys/Saturated Colors\0";
    ui_category = SECTION_SPLIT;
    ui_category_closed = true;
> = 0;

uniform float3 SPLITTONE_SHADOWS <
  	ui_type = "color";
  	ui_label="Tint A";
  	ui_category = SECTION_SPLIT;
    ui_category_closed = true;    
> = float3(0.5, 0.5, 0.5);

uniform float3 SPLITTONE_HIGHLIGHTS <
  	ui_type = "color";
  	ui_label="Tint B";
  	ui_category = SECTION_SPLIT;
    ui_category_closed = true;    
> = float3(0.5, 0.5, 0.5);

uniform float SPLITTONE_BALANCE <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Balance";
    ui_category = SECTION_SPLIT;
    ui_category_closed = true;
> = 0.0;

uniform int SPLITTONE_BLEND <
	ui_type = "combo";
    ui_label = "Blend Mode";
	ui_items = " Soft Light\0 Overlay\0";
    ui_category = SECTION_SPLIT;
    ui_category_closed = true;
> = 0;

uniform bool BYPASS_CB <
    ui_label = CONCAT("Bypass ", LABEL_CB);
    ui_category = SECTION_CB;
    ui_category_closed = true;
> = false;

uniform float2 CB_SHAD <
  	ui_type = "drag";
  	ui_label="Hue / Saturation: Shadows";
    ui_min = 0.00; ui_max = 1.00;  
  	ui_category = SECTION_CB;
    ui_category_closed = true;    
> = float2(0.0, 0.0);

uniform float2 CB_MID <
  	ui_type = "drag";
  	ui_label="Hue / Saturation: Midtones";
    ui_min = 0.00; ui_max = 1.00;  
  	ui_category = SECTION_CB;
    ui_category_closed = true;    
> = float2(0.0, 0.0);

uniform float2 CB_HI <
  	ui_type = "drag";
  	ui_label="Hue / Saturation: Highlights";
    ui_min = 0.00; ui_max = 1.00;  
  	ui_category = SECTION_CB;
    ui_category_closed = true;    
> = float2(0.0, 0.0);

uniform bool BYPASS_SPECIAL <
    ui_label = CONCAT("Bypass ", LABEL_SPECIAL);
    ui_category = SECTION_SPECIAL;
    ui_category_closed = true;
> = false;

uniform float SPECIAL_BLEACHBP <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Bleach Bypass (Gamma Corrected)";
    ui_category = SECTION_SPECIAL;
    ui_category_closed = true;
> = 0.0;

uniform float2 SPECIAL_GAMMA_LUM_CHROM <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Gamma on Luma | Chroma";
    ui_category = SECTION_SPECIAL;
    ui_category_closed = true;
> = float2(0.0, 0.0);

uniform bool ENABLE_VIGNETTE <
	ui_label = "Enable Vignette Effect";
    ui_tooltip = "Allows two kinds of vignette effects:\n\n" 
    "Mechanical Vignette:   The insides of a camera lens occlude light at the corners of the field of view.\n\n"
    "Sensor Vignette:       Projection of light onto sensor plane causes a secondary vignette effect.\n"
    "                       Incident angle of light hitting the sensor and its travel distance affect light intensity.";
    ui_category = "Vignette";
    ui_category_closed = true;
> = false;

uniform float VIGNETTE_RADIUS_MECH <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Mechanical Vignette: Radius";
    ui_category = "Vignette";
    ui_category_closed = true;
> = 0.525;

uniform float VIGNETTE_BLURRYNESS_MECH <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 1.0;
	ui_label = "Mechanical Vignette: Blurryness";
    ui_category = "Vignette";
    ui_category_closed = true;
> = 0.8;

uniform float VIGNETTE_RATIO <
	ui_type = "drag";
	ui_min = -1.0; ui_max = 1.0;
	ui_label = "Mechanical Vignette: Shape";
    ui_category = "Vignette";
    ui_category_closed = true;
> = 0.0;

uniform float VIGNETTE_RADIUS_SENSOR <
	ui_type = "drag";
	ui_min = 0.0; ui_max = 2.0;
	ui_label = "Sensor Vignette:     Scale";
    ui_category = "Vignette";
    ui_category_closed = true;
> = 1.0;

uniform int VIGNETTE_BLEND_MODE <
	ui_type = "combo";
    ui_label = "Vignette Blending Mode";
	ui_items = "Standard\0HDR simulation\0HDR simulation (protect tones)\0";
    ui_category = "Vignette";
    ui_category_closed = true;
> = 1;

uniform int DITHER_BIT_DEPTH <
	ui_type = "combo";
    ui_label = "Dithering";
	ui_items = " Off\0 6 Bit\0 8 Bit\0 10 Bit\0 12 Bit\0";
    ui_category = "Utility";
    ui_category_closed = true;
> = 2;

uniform bool UTILITY_DISPLAY_COLORMAP <
    ui_label = "Display Colormap";
    ui_category = "Utility";
    ui_category_closed = true;
> = false;
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

#pragma warning(disable : 3571) //pow(f, e) will not work etc etc

uniform float FRAMETIME < source = "frametime";  >;
uniform uint FRAMECOUNT  < source = "framecount"; >;
uniform bool OVERLAY_ACTIVE < source = "overlay_open"; >;

#include ".\MartysMods\mmx_global.fxh"
#include ".\MartysMods\mmx_math.fxh"
#include ".\MartysMods\mmx_colorspaces.fxh"
#include ".\MartysMods\mmx_texture.fxh"

//An analysis covering all possible colors yielded these magic numbers
//as viable minima for single channel and compounded error to neutral LUT
//Results vary a bit for analysis using colors weighted by natural occurence
//and average weighting entire RGB cube. 
//Values were picked that score well in both and R*B < 4096 (DX9 limit)

/*
//for HSV indexing - allows for the grey line to be parallel to a lattice axis
//improving quality on greys but maximum error for selected colors increases
//and it doesn't allow for C1+ continuous sampling.
 #define LUT_DIM_R    43
 #define LUT_DIM_G    64
 #define LUT_DIM_B    94
 */

//Values picked after perceptual luma so that G > R > B in precision. 
 #define LUT_DIM_R    51 
 #define LUT_DIM_G    84
 #define LUT_DIM_B    34

#define LUT_DIM_X (LUT_DIM_R * LUT_DIM_B)
#define LUT_DIM_Y (LUT_DIM_G)

texture2D LUTFlattened	                { Width = LUT_DIM_X;   Height = LUT_DIM_Y;                    Format = RGBA32F;  	};
sampler2D sLUTFlattened		            { Texture = LUTFlattened;   };

#if _COMPUTE_SUPPORTED 
storage stLUTFlattened		            { Texture = LUTFlattened;   };
#else 
texture2D LUTAtlas	                    { Width = LUT_DIM_X;   Height = LUT_DIM_Y * NUM_SECTIONS;     Format = RGBA32F;  	};
sampler2D sLUTAtlas		                { Texture = LUTAtlas;       };
#endif

#if ENABLE_SOLARIS_REGRADE_PARITY != 0
texture2D ColorInputHDRTex			    { Width = BUFFER_WIDTH;   Height = BUFFER_HEIGHT;                Format = RGBA16F; };
sampler ColorInput 	{ Texture = ColorInputHDRTex; MinFilter=POINT; MipFilter=POINT; MagFilter=POINT; };
#else 
texture ColorInputTex : COLOR;
sampler ColorInput 	{ Texture = ColorInputTex; MinFilter=POINT; MipFilter=POINT; MagFilter=POINT; };
#endif

struct VSOUT
{
	float4 vpos : SV_Position;
    float4 uv : TEXCOORD0;
};

/*=============================================================================
	Functions
=============================================================================*/

/*=============================================================================
	Color Remapper
=============================================================================*/ 

struct ColorRemapperParams 
{
    float3 huemod[7];    
};

float3 color_remapper(in float3 rgb, ColorRemapperParams params)
{
    static const float hue_nodes[8] = {	 0.0, 1.0/12.0, 2.0/12.0, 4.0/12.0, 6.0/12.0, 8.0/12.0, 10.0/12.0, 1.0};
    float hue = Colorspace::rgb_to_hsl(rgb).x;

    float risingedges[7]; 
    [unroll]for(int j = 0; j < 7; j++)
        risingedges[j] = linearstep(hue_nodes[j], hue_nodes[j + 1], hue);

    float hueweights[7];    
    hueweights[0] = ((1.0 - risingedges[0]) + risingedges[6]); //this goes over the 2 pi boundary, so this needs special treatment
    [unroll]for(int j = 1; j < 7; j++) 
        hueweights[j] = ((1.0 - risingedges[j]) * risingedges[j - 1]); 

    float3 oklab = Colorspace::rgb_to_oklab(rgb);
    float3 ret = 0;

    [loop]
    for(int hue = 0; hue < 7; hue++)
    {
        float w = hueweights[hue];
        w = w * w * (3.0 - 2.0 * w); //smoothstep - integral is energy conserving vs linear, otherwise we'd need to normalize weights here!!

        if(w < 0.000001) continue;
        float3 new_hue = oklab;

        new_hue.x = pow(max(0, new_hue.x), exp2(-params.huemod[hue].z * 4 * length(new_hue.yz))); //better, leaves greys untouched. Not sure if sqrt is needed
        float2 huesc; sincos(-PI * params.huemod[hue].x, huesc.x, huesc.y);    
        new_hue.yz = Math::rotate_2D(new_hue.yz, Math::get_rotator(-PI * params.huemod[hue].x));

        [flatten]
        if(params.huemod[hue].y < 0) //reduce sat ->saturation 0%-100%
        {
            new_hue.yz *= 1 + params.huemod[hue].y; 
        }
        else //increase saturation -> vibrance
        {
            float sat = length(new_hue.yz);
            new_hue.yz /= sat + 1e-7;
            sat = pow(sat * 2, exp2(-params.huemod[hue].y * 0.5)) * 0.5;
            new_hue.yz *= sat;
        }

        ret += new_hue * w;
    }

    ret = Colorspace::oklab_to_rgb(ret);
    ret = saturate(ret);
    return ret;
}

/*=============================================================================
	Tone Curve
=============================================================================*/

struct ToneCurveParams 
{
    float blacks, darks, lights, highlights, darkwash_amt, darkwash_range;
};

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

float tonecurve(float x, ToneCurveParams params)
{    
    float s = x;

    x += shadows(s) * params.blacks;
    x += darks(x) * params.darks;
    x += lights(s) * params.lights;
    x += highlights(x) * params.highlights;

    float t = x / (params.darkwash_range + 1e-6);
    float dw = (10.0 * params.darkwash_range  - x) * t * t * (1.0 / 31.25) + params.darkwash_range;
    x = max(x, (dw - x) * params.darkwash_amt + x);

	return x;
}

float3 tonecurve(float3 rgb, ToneCurveParams params)
{    
    rgb.x = tonecurve(rgb.x, params);
    rgb.y = tonecurve(rgb.y, params);
    rgb.z = tonecurve(rgb.z, params);
    return rgb;
}

/*=============================================================================
	Levels
=============================================================================*/

struct LevelsParams
{
    float black_in, black_out, white_in, white_out; 
};

float3 input_remap( float3 x, LevelsParams params)
{
    x = linearstep(params.black_in, params.white_in + 1e-6, x);   
    x = lerp(params.black_out, params.white_out, x);
	return x;
}

/*=============================================================================
	Lift Gamma Gain
=============================================================================*/

struct LiftGammaGainParams
{
    float3 lift, gamma, gain;
    int mode;
};

float3 lgg(float3 x, LiftGammaGainParams params)
{
    switch(params.mode)
    {
        //https://en.wikipedia.org/wiki/ASC_CDL
        case 0: 
        {    
            x = pow(saturate((x * params.gain) + params.lift), params.gamma);
            break; //can't early out here due to DX compiler being a jackass (uninitialized variable...)
        }
        case 1:
        {
            x = pow(saturate(lerp(params.lift, params.gain, x)), params.gamma);
            break;
        }
    }
    return x;
}

/*=============================================================================
	Split Toning
=============================================================================*/

struct SplitToneParams 
{
    uint mode;
    uint blend_mode;
    float balance;
    float3 toneA, toneB;
};

float3 extended_overlay(float3 base, float3 blend)
{
    float sharpness = 7; //max ~100 without precision loss
    float3 poly_tri = 1 - pow(pow(base, sharpness) + pow(1 - base, sharpness), rcp(sharpness)); //form smooth triangle (vs hard triangle in regular overlay)
    return base + poly_tri * (blend * 2 - 1);
}

float3 soft_light(float3 base, float3 blend)
{	
	return pow(base, exp2(1 - 2 * blend));
}

float3 splittone(float3 c, SplitToneParams params)
{
    float luma = Colorspace::get_srgb_luma(c);
    float balance = 0;

    switch(params.mode)
    {
        case 0:
        {
            float expo = exp2(params.balance * 3 - 1.13); //adjust range so it's perceptually balanced at 0, gamma 2.2
            balance = expo > 1 ? pow(luma, expo) : 1 - pow(1 - luma, rcp(expo));
            break;
        }
        case 1: 
        {
            float3 v_sat = c - luma;
            float3 k = v_sat < 0.0.xxx ? c : 1 - c;
            k /= abs(v_sat) + 1e-6;
            float min_k = min(min(k.x, k.y), k.z); //which component saturates earliest?
            float sat = saturate(rcp(1 + min_k));

            float expo = exp2(params.balance * 6);
            balance = expo > 1 ? pow(sat, expo) : 1 - pow(1 - sat, rcp(expo));
            break;
        }            
    }

    float3 tintcolor = Colorspace::oklab_to_rgb(lerp(Colorspace::rgb_to_oklab(params.toneA),
                                                        Colorspace::rgb_to_oklab(params.toneB),
                                                        balance));
                                        
    c = params.blend_mode == 1 ? extended_overlay(c, tintcolor) : soft_light(c, tintcolor);                        
    return c;
}

/*=============================================================================
	Color Balance
=============================================================================*/

struct ColorBalanceParams
{
    float2 chroma_sh, chroma_mid, chroma_hi; //hue, sat
};

float3 color_balance(float3 c, ColorBalanceParams params)
{
    //better use some perceptually well fitting estimate
    float luma = Colorspace::linear_to_srgb(dot(Colorspace::srgb_to_linear(c), float3(0.2126729, 0.7151522, 0.0721750))).x;

    float3 offsetSMH = float3(0, 0.5, 1);
    float3 widthSMH = float3(2.0, 1.0, 2.0);

    float3 weightSMH = saturate(1 - 2 * abs(luma - offsetSMH) / widthSMH);
    weightSMH = weightSMH * weightSMH * (3 - 2 * weightSMH);
    weightSMH *= weightSMH; //these do not sum up to 1.0, makes no sense in Lightroom either
    weightSMH.z *= 2.0;

    float3 tintcolorS = Colorspace::hsl_to_rgb(float3(frac(0.5 + params.chroma_sh.x), 1, 0.5));
    float3 tintcolorM = Colorspace::hsl_to_rgb(float3(frac(0.5 + params.chroma_mid.x), 1, 0.5));
    float3 tintcolorH = Colorspace::hsl_to_rgb(float3(frac(0.5 + params.chroma_hi.x), 1, 0.5));

    return length(c) * normalize(pow(c, exp2(tintcolorS * weightSMH.x * params.chroma_sh.y*params.chroma_sh.y
                                           + tintcolorM * weightSMH.y * params.chroma_mid.y*params.chroma_mid.y
                                           + tintcolorH * weightSMH.z * params.chroma_hi.y*params.chroma_hi.y)));
}

/*=============================================================================
	Adjustments
=============================================================================*/

struct AdjustmentsParams
{
    float exposure, contrast, gamma, vibrance, saturation, filmic_gamma;
};

float3 adjustments(float3 col, AdjustmentsParams params)
{
    col = Colorspace::srgb_to_linear(col);
    col *= exp2(params.exposure); //exposure in linear space - this makes no _visual_ difference but alters the response of the exposure curve
    col = Colorspace::linear_to_srgb(col);
    col = saturate(col);

    float3 tcol = col * params.filmic_gamma * (params.filmic_gamma > 0 ? 6.0 : 0.6);
    col = (tcol + col) / (tcol + 1);
    col = saturate(col);

    col = pow(col, exp2(-params.gamma));
    float3 contrasted = col - 0.5;
    contrasted = (contrasted / (0.5 + abs(contrasted))) + 0.5; //CJ.dk
    col = lerp(col, contrasted, params.contrast);

    float luma = Colorspace::linear_to_srgb(dot(Colorspace::srgb_to_linear(col), float3(0.2126729, 0.7151522, 0.0721750))).x;
    float3 v_sat = col - luma;

    float3 k = v_sat < 0.0.xxx ? col : 1 - col;
    k /= abs(v_sat) + 1e-6;
    float min_k = min(min(k.x, k.y), k.z); //which component saturates earliest?

    float vib = params.vibrance;
    vib *= vib > 0 ? min_k * rsqrt(vib * vib + min_k * min_k) : saturate(1 - rcp(1 + min_k));

    float final_sat = vib * (1 + params.saturation) + params.saturation;
    final_sat = clamp(final_sat, -1, min_k); //force limit to prevent hueshifts

    col += v_sat * final_sat;
    return col;
}

/*=============================================================================
	Special FX
=============================================================================*/

struct SpecialParams
{
    float bleach;
    float gamma_luma;
    float gamma_chroma;
};

float3 specialfx(float3 c, SpecialParams params)
{
    //after removing all back and forth math involved with negative film process
    //at the end bleach bypass is just subtractive (multiplicative) mix with image luma

    //better use some perceptually well fitting estimate
    float luma = Colorspace::linear_to_srgb(dot(Colorspace::srgb_to_linear(c), float3(0.2126729, 0.7151522, 0.0721750))).x;
    c *= lerp(1.0, luma, params.bleach);    
    c = pow(saturate(c), rcp(1.0 + params.bleach * 0.5));

    float k = 1.73205; //sqrt(3)
    float l = length(c);
    float3 ch = c / (l + 1e-6);

    ch = pow(ch, exp2(params.gamma_chroma));
    l = pow(l / k, exp2(-params.gamma_luma)) * k;

    c = normalize(ch + 1e-6) * l; 

    return c;
}

/*=============================================================================
	White Balance / Calibration
=============================================================================*/

float3 blackbody_xyz(float temperature) 
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

    float3 XYZ;
    XYZ.y = 1.0;
    XYZ.x = XYZ.y / y * x;
    XYZ.z = XYZ.y / y * (1.0 - x - y);

    return XYZ;
}

float3x3 chromatic_adaptation(float3 xyz_src, float3 xyz_dst)
{
    //https://en.wikipedia.org/wiki/LMS_color_space
    //Hunt-Pointer-Estevez transformation, old LMS <-> XYZ, also called von Kries transform
    //using newer XYZ <-> LMS matrices won't work here
    const float3x3 xyz_to_lms = float3x3(0.4002, 0.7076, -0.0808,           
                                        -0.2263, 1.1653, 0.0457,
                                         0,0,0.9182);
    const float3x3 lms_to_xyz = float3x3(1.8601 ,  -1.1295, 0.2199,
                                        0.3612, 0.6388 , -0.0000,
                                        0, 0, 1.0891);                                

    float3 lms_src = mul(xyz_src, xyz_to_lms);
    float3 lms_dst = mul(xyz_dst, xyz_to_lms);

    float3x3 von_kries_transform = float3x3(lms_dst.x / lms_src.x, 0, 0,
                                            0, lms_dst.y / lms_src.y, 0,
                                            0, 0, lms_dst.z / lms_src.z);

    return mul(mul(xyz_to_lms, von_kries_transform), lms_to_xyz);
}

struct CalibrationParams
{
    float temperature;
    float2 lab_offset;
    float3 primary_hues;
    float3 primary_sat;
    int mode;
};

float3 calibration(float3 rgb, CalibrationParams params)
{
    float3 xyz_src = blackbody_xyz(6500.0);
    float3 xyz_dst = blackbody_xyz(params.temperature);

    float3 adjusted = Colorspace::rgb_to_xyz(rgb);
    adjusted = mul(adjusted, chromatic_adaptation(xyz_src, xyz_dst));
    adjusted = Colorspace::xyz_to_rgb(adjusted);
    adjusted = saturate(adjusted);

    float3 lab = Colorspace::rgb_to_oklab(adjusted);
    lab.yz += params.lab_offset * 0.05;
    adjusted = Colorspace::oklab_to_rgb(lab);
    adjusted = saturate(adjusted);

    float3 c = adjusted;
    float minc = min(min(c.x, c.y), c.z);
    
    if(params.mode == 0 || params.mode == 2) c -= minc;

    float3 prim_R = float3(1, saturate(params.primary_hues.x), saturate(-params.primary_hues.x));
    float3 prim_G = float3(saturate(-params.primary_hues.y), 1, saturate(params.primary_hues.y));
    float3 prim_B = float3(saturate(params.primary_hues.z), saturate(-params.primary_hues.z), 1);
    
    if(params.mode != 0)
    {
        prim_R = lerp(dot(prim_R, 0.33333), prim_R, 1 + params.primary_sat.x);
        prim_G = lerp(dot(prim_G, 0.33333), prim_G, 1 + params.primary_sat.y);
        prim_B = lerp(dot(prim_B, 0.33333), prim_B, 1 + params.primary_sat.z);
    }
    else 
    {
        prim_R = lerp(dot(prim_R, 0.33333), prim_R, dot(c / dot(c, 1), 1 + params.primary_sat));
        prim_G = lerp(dot(prim_G, 0.33333), prim_G, dot(c / dot(c, 1), 1 + params.primary_sat));
        prim_B = lerp(dot(prim_B, 0.33333), prim_B, dot(c / dot(c, 1), 1 + params.primary_sat));
    }    

    prim_R = normalize(prim_R);
    prim_G = normalize(prim_G);
    prim_B = normalize(prim_B);

    c = normalize(c.r * prim_R + c.g * prim_G + c.b * prim_B) * length(c); 

    if(params.mode == 0 || params.mode == 2) c += minc;
    c = saturate(c);
    return c;
}

/*=============================================================================
	Unused
=============================================================================*/  

//calculates saturation very similar to how Adobe LrC does it
float3 colorsat_lightroom(float3 c)
{
    float minc = min(min(c.x, c.y), c.z);
    c -= minc;
    float maxc = max(max(c.x, c.y), c.z);

    float sat = 2.0;
    c = lerp(dot(c, 0.33333), c, sat);
    c *= maxc / max(max(c.x, c.y), c.z);
    c += minc;

    return c;
}

float3 apply_color_op(float3 col, int op)
{
    ColorRemapperParams CRParams;
    CRParams.huemod = {COLOR_REMAP_RED, COLOR_REMAP_ORANGE, COLOR_REMAP_YELLOW, COLOR_REMAP_GREEN, COLOR_REMAP_AQUA, COLOR_REMAP_BLUE, COLOR_REMAP_MAGENTA};

    ToneCurveParams TCParams;
    TCParams.blacks = TONECURVE_SHADOWS;
    TCParams.darks = TONECURVE_DARKS;
    TCParams.lights = TONECURVE_LIGHTS; 
    TCParams.highlights = TONECURVE_HIGHLIGHTS;
    TCParams.darkwash_amt = TONECURVE_DARKWASH_INT;
    TCParams.darkwash_range = TONECURVE_DARKWASH_RANGE;

    LevelsParams LParams;
    LParams.black_in = INPUT_BLACK_LVL / 255.0;
    LParams.black_out = OUTPUT_BLACK_LVL / 255.0;
    LParams.white_in = INPUT_WHITE_LVL / 255.0;
    LParams.white_out = OUTPUT_WHITE_LVL / 255.0;

    LiftGammaGainParams LGGParams;
    LGGParams.lift = INPUT_LIFT_COLOR - 0.5;
    LGGParams.gamma = 1.0 - INPUT_GAMMA_COLOR + 0.5;
    LGGParams.gain = INPUT_GAIN_COLOR + 0.5;
    LGGParams.mode = INPUT_LGG_MODE;

    SplitToneParams STParams;
    STParams.mode = SPLITTONE_MODE;
    STParams.blend_mode = SPLITTONE_BLEND;
    STParams.balance = SPLITTONE_BALANCE;
    STParams.toneA = SPLITTONE_SHADOWS;
    STParams.toneB = SPLITTONE_HIGHLIGHTS;

    ColorBalanceParams CBParams;
    CBParams.chroma_sh = CB_SHAD;
    CBParams.chroma_mid = CB_MID;
    CBParams.chroma_hi = CB_HI;

    AdjustmentsParams AParams;
    AParams.exposure = GRADE_EXPOSURE;
    AParams.contrast = GRADE_CONTRAST;
    AParams.gamma = GRADE_GAMMA;
    AParams.vibrance = GRADE_VIBRANCE;
    AParams.saturation = GRADE_SATURATION;
    AParams.filmic_gamma = GRADE_FILMIC_GAMMA;

    SpecialParams SParams;
    SParams.bleach = SPECIAL_BLEACHBP;
    SParams.gamma_luma = SPECIAL_GAMMA_LUM_CHROM.x;
    SParams.gamma_chroma = SPECIAL_GAMMA_LUM_CHROM.y;

    CalibrationParams CParams;
    CParams.temperature = INPUT_COLOR_TEMPERATURE;
    CParams.lab_offset = float2(INPUT_COLOR_LAB_A, INPUT_COLOR_LAB_B);
    CParams.primary_hues = INPUT_COLOR_PRIMARY_HUE;
    CParams.primary_sat = INPUT_COLOR_PRIMARY_SAT;
    CParams.mode = INPUT_COLOR_PRIMARY_MODE;

    switch(op)
    {
        case GRADE_ID_LEVELS:       if(!BYPASS_LEVELS)      col = input_remap(col, LParams);    break;
        case GRADE_ID_ADJ:          if(!BYPASS_ADJ)         col = adjustments(col, AParams);    break;
        case GRADE_ID_LGG:          if(!BYPASS_LGG)         col = lgg(col, LGGParams);          break;
        case GRADE_ID_CALIB:        if(!BYPASS_CALIB)       col = calibration(col, CParams);    break;
        case GRADE_ID_REMAP:        if(!BYPASS_REMAP)       col = color_remapper(col, CRParams);break;
        case GRADE_ID_TONECURVE:    if(!BYPASS_TONECURVE)   col = tonecurve(col, TCParams);     break;
        case GRADE_ID_SPLIT:        if(!BYPASS_SPLIT)       col = splittone(col, STParams);     break;
        case GRADE_ID_CB:           if(!BYPASS_CB)          col = color_balance(col, CBParams); break;      
        case GRADE_ID_SPECIAL:      if(!BYPASS_SPECIAL)     col = specialfx(col, SParams);      break;   
    };

    return col;
}

float3 dither(in int2 pos, int bit_depth)
{    
    const float lsb = exp2(bit_depth) - 1;
    const float2 magicdot = float2(0.75487766624669276, 0.569840290998); 
    const float3 magicadd = float3(0, 0.025, 0.0125) * dot(magicdot, 1);

    float3 dither = frac(dot(pos, magicdot) + magicadd);       
    dither = dither - 0.5;
    dither *= 0.99; //so if added to source color, it just does not spill over to next bucket
    dither /= lsb;
    return dither;
}

float3 draw_lut(float2 coord, int3 volumesize) //need float2 due to DX9 being a jackass
{
    coord.y %= volumesize.y;
    float3 col = float3(coord.x % volumesize.x, coord.y, floor(coord.x / volumesize.x));
    col = saturate(col / (volumesize - 1.0));  
    return saturate(col);
}

float3 sample_lut(sampler s, float3 col, int atlas_idx)
{
    col = saturate(col);
    const int3 size = int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B);
    return Texture::sample3D_tetrahedral(s, col, size, atlas_idx).rgb;   
}

float3 apply_vignette(float2 uv, float3 color)
{
    float2 viguv = uv * 2.0 - 1.0;
    viguv   -= viguv * saturate(float2(VIGNETTE_RATIO, -VIGNETTE_RATIO));
    viguv.x *= BUFFER_ASPECT_RATIO.y;

    float r = sqrt(dot(viguv, viguv) / dot(BUFFER_ASPECT_RATIO, BUFFER_ASPECT_RATIO));

    float vig = 1.0;
            
    float rf = r * VIGNETTE_RADIUS_SENSOR;
    float vigsensor = 1.0 + rf * rf; //cos is 1/sqrt(1+r*r) here, so 1/(1+r*r)^2 is cos^4
    vig *= rcp(vigsensor * vigsensor);
  
    float2 radii = VIGNETTE_RADIUS_MECH + float2(-VIGNETTE_BLURRYNESS_MECH * VIGNETTE_RADIUS_MECH * 0.2, 0);          

    float2 vsdf = r - radii;
    vig *= saturate(1 - vsdf.x / abs(vsdf.y - vsdf.x));

    switch(VIGNETTE_BLEND_MODE)
    {
        case 0:
            color *= vig; 
            break;
        case 1:
            color = color * rcp(1.03 - color);
            color *= vig;
            color = 1.03 * color * rcp(color + 1.0);
            break;
        case 2:
            float3 oldcolor = color;
            color = color * rcp(1.03 - color);
            color *= vig;
            color = 1.03 * color * rcp(color + 1.0);
            color = normalize(oldcolor + 1e-5) * length(color);
            break;
    }
    return color;
}

/*=============================================================================
	Shader Entry Points
=============================================================================*/

VSOUT MainVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv.xy); o.uv.zw = 0;
    return o;
}

#if _COMPUTE_SUPPORTED

struct CSIN 
{
    uint3 groupthreadid     : SV_GroupThreadID;         
    uint3 groupid           : SV_GroupID;            
    uint3 dispatchthreadid  : SV_DispatchThreadID;     
    uint threadid           : SV_GroupIndex;
};

void LUTBuildCS(in CSIN i) //1D dispatch for all colors
{ 
    const uint3 volume_size = uint3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B);

    uint id = i.dispatchthreadid.x;
    uint3 volume_pos;
    volume_pos.x = id % volume_size.x; id /= volume_size.x;
    volume_pos.y = id % volume_size.y; id /= volume_size.y;
    volume_pos.z = id;
    float3 rgb = saturate(volume_pos / (volume_size - 1.0));

    int op_sequence[NUM_SECTIONS] = {NODE1,NODE2,NODE3,NODE4,NODE5,NODE6,NODE7,NODE8,NODE9};  

    [loop]for(int op_slot = 0; op_slot < NUM_SECTIONS; op_slot++)
    {
        int op = op_sequence[op_slot];
        if(op == GRADE_ID_NONE) continue;
        rgb = apply_color_op(rgb, op); 
    } 

    uint2 write_pos = uint2(volume_pos.x + volume_pos.z * volume_size.x, volume_pos.y);
    tex2Dstore(stLUTFlattened, write_pos, float4(rgb, 1));
}

#else //_COMPUTE_SUPPORTED

VSOUT LUTAtlasVS(in uint id : SV_VertexID)
{ 
    int op_sequence[NUM_SECTIONS] = {NODE1,NODE2,NODE3,NODE4,NODE5,NODE6,NODE7,NODE8,NODE9};
    int op_slot = id / 3u;
    int op = op_sequence[op_slot];
    uint write_slot = op_slot;    
    for(uint j = 0; j < op_slot; j++)
        if(op_sequence[j] == GRADE_ID_NONE) 
            write_slot--;

    VSOUT o; 
    o.uv.x = (id % 3u == 2) ? 2.0 : 0.0;
    o.uv.y = (id % 3u == 1) ? 2.0 : 0.0;

    float2 target_uv = o.uv.xy;
    target_uv.y = (target_uv.y + write_slot) / NUM_SECTIONS;   
    o.vpos = float4(target_uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);  

    o.uv.zw = op; 
    o.vpos = op == GRADE_ID_NONE ? 0 : o.vpos;
    return o;
}

void LUTAtlasPS(in VSOUT i, out float4 o : SV_Target0)
{
    if(any(saturate(i.uv.xy - 1.0))) discard;
    int op = round(i.uv.z);
    float3 col = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    col = apply_color_op(col, op);
    col = saturate(col);
    o.rgb = col;
    o.w = 1; 
}

VSOUT LUTFlattenVS(in uint id : SV_VertexID)
{
    VSOUT o;
    FullscreenTriangleVS(id, o.vpos, o.uv.xy);

    int op_sequence[NUM_SECTIONS] = {NODE1,NODE2,NODE3,NODE4,NODE5,NODE6,NODE7,NODE8,NODE9};
    int op_count = 0;
    for(int j = 0; j < NUM_SECTIONS; j++) 
        op_count += op_sequence[j] != GRADE_ID_NONE ? 1 : 0;
    o.uv.zw = op_count;
    return o;    
}

void LUTFLattenPS(in VSOUT i, out float4 o : SV_Target0)
{
    float3 col = draw_lut(floor(i.vpos.xy), int3(LUT_DIM_R, LUT_DIM_G, LUT_DIM_B));
    int op_count = round(i.uv.z);
    for(int op = 0; op < op_count; op++)
        col = sample_lut(sLUTAtlas, col, op);     
    o.rgb = col;
    o.w = 1;
}

#endif //_COMPUTE_SUPPORTED

void LUTApplyPS(in VSOUT i, out float3 o : SV_Target0)
{    
    float3 col = tex2D(ColorInput, i.uv.xy).rgb;  

    if(ENABLE_VIGNETTE)
        col = apply_vignette(i.uv.xy, col);
        
  
    float3 map_a = float3(frac(i.uv.x * 2), i.uv.y*1.3333, 0.5);
    float3 map_b = float3(frac(i.uv.x * 2), 1, i.uv.y*1.3333);
    
    float3 colormap = saturate(i.uv.x > 0.5 ? map_b : map_a);        

    if(UTILITY_DISPLAY_COLORMAP)
    {
        col = Colorspace::hsl_to_rgb(colormap);
        col = i.uv.y > 0.6666 ? i.uv.x : col;
    } 

    col = sample_lut(sLUTFlattened, col, 0);
  
    if(DITHER_BIT_DEPTH > 0) 
        col += dither(i.vpos.xy, DITHER_BIT_DEPTH * 2 + 4);
  
    o = col;
}

/*=============================================================================
	Techniques
=============================================================================*/

technique MartysMods_ReGrade
<
    ui_label = "iMMERSE Pro: ReGrade";
    ui_tooltip =        
        "                               MartysMods - ReGrade                               \n"
        "                     MartysMods Epic ReShade Effects (iMMERSE)                    \n"
        "               Official versions only via https://patreon.com/mcflypg             \n"
        "__________________________________________________________________________________\n"
        "\n"
        "ReGrade is a comprehensive framework for color grading and -correction.           \n"
        "It features many tools commonly used by photographers and video editors, combined \n"
        "in one modular, intuitive and highly optimized framework.                         \n"
        "\n"
        "\n"
        "Visit https://martysmods.com for more information.                                \n"
        "\n"       
        "__________________________________________________________________________________\n"
        "Version: 0.13";
>
{
#if _COMPUTE_SUPPORTED
    #define GROUP_SIZE 256
    pass 
    { 
        ComputeShader = LUTBuildCS<GROUP_SIZE, 1>;
        DispatchSizeX = CEIL_DIV(LUT_DIM_R*LUT_DIM_G*LUT_DIM_B, GROUP_SIZE); 
        DispatchSizeY = 1; 
    }
#else    
    pass
	{
		VertexShader = LUTAtlasVS;
		PixelShader = LUTAtlasPS;
        RenderTarget = LUTAtlas;
        PrimitiveTopology = TRIANGLELIST;
		VertexCount = 3 * NUM_SECTIONS;
	}
    pass
	{
		VertexShader = LUTFlattenVS;
		PixelShader = LUTFLattenPS;
        RenderTarget = LUTFlattened;
	}
#endif
    pass    
	{
		VertexShader = MainVS;
		PixelShader = LUTApplyPS;
	}
}