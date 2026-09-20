/*
 * Copyright (C) 2023
 * File Name: db_work.c
 * Project:
 * Description: my_sql 数据库操作模块
 * File Created:
 * Author:
 * Modified By: lj
 * -----
 * HISTORY:
 */
#include "main.h"
#include "assist_func.h"
#include "trina_log.h"
#include "timed_check.h"
#include "db_work.h"
#include "other_work.h"
#include "db_work_ex.h"

// 4: Remote&Local control mode
// const TableAddressStruct emuTableHoldAddr0 []
// {
// 	{4, 4},
// };
// 1000-1002: Mode configuration - Active power dispatch mode, Reactive power dispatch mode, Dispatch Priority
// 功率目标与电力因子
// 1010-1012: AC active power target, AC reactive power target, Power factor
// 电网连接操作参数
// 1030-1046: Grid-connected operating parameters, LVRT & HVRT settings, Anti-islanding, Transformer settings
// 电网标准保护参数
// 1050-1108: Grid Standard Protection Parameters (overvoltage, undervoltage, overfrequency, underfrequency protections and their timings)
// 电网连接的电压与频率
// 1120-1126: Allowable voltage and frequency offsets for grid connection, Power-on delay, Soft start time
// 频率适应
// 1140-1192: Frequency Adaptation parameters, including limits, compensation curves, and dead zones
// 电网成型参数
// 1200-1211: Grid-forming parameters, VSG-related settings
// 反应调度曲线
// 1250-1300: Reactive dispatch curve parameters, including curve points and reference voltage settings
// 功率-频率曲线 (P-Freq Curve)
// 1310-1334: P-Freq curve parameters, including curve points and response times
// 功率-功率曲线 (Q-P Curve)
// 1340-1364: Q-P curve parameters
// 功率-电压曲线 (P-U Curve)
// 1370-1396: P-U curve parameters
// 系统参数
// 1450-1459: System Parameters, including rated voltage, frequency, grid-connected/off-grid mode, carrier settings
// 电池参数
// 1470-1479: Battery Parameters, including charge/discharge protection and insulation resistance
// 保留地址区域
// 5-19: Reserved addresses
// 电网连接操作参数（LVRT/HVRT详细设置）
// 1490-1500: Grid-connected operation parameters - LVRT enable setting, start voltage point, reactive current compensation, active coefficient, HVRT enable setting, and other related settings
const TableAddressStruct emuTableHoldAddr[] =
	{
		{4, 6},
		{1000, 1002},
		{1010, 1012},
		{1500, 1547},

};
// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st emuHoldIsNotU16Regs[] =
	{
		{1010, TpyeLcShort},
		{1011, TpyeLcShort},
		{1012, TpyeLcShort},
		{1065, TpyeLcShort},
		{1066, TpyeLcShort},
		{1067, TpyeLcShort},
		{1068, TpyeLcShort},
		{1069, TpyeLcShort},
};
const TableAddressStruct emuTableInputAddr[] =
	{
		{100, 168},
		{200, 227},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st emuInputIsNotU16Regs[] =
	{
		{100, TpyeLcUnInt_H},
		{101, TpyeLcUnInt_L},
		{102, TpyeLcUnInt_H},
		{103, TpyeLcUnInt_L},

		{109, TpyeLcUnInt_H},
		{110, TpyeLcUnInt_L},
		{111, TpyeLcUnInt_H},
		{112, TpyeLcUnInt_L},
		{113, TpyeLcUnInt_H},
		{114, TpyeLcUnInt_L},
		{115, TpyeLcUnInt_H},
		{116, TpyeLcUnInt_L},
		{117, TpyeLcUnInt_H},
		{118, TpyeLcUnInt_L},
		{119, TpyeLcUnInt_H},
		{120, TpyeLcUnInt_L},

		{123, TpyeLcInt_H},
		{124, TpyeLcInt_L},
		{125, TpyeLcInt_H},
		{126, TpyeLcInt_L},
		{127, TpyeLcInt_H},
		{128, TpyeLcInt_L},
		{129, TpyeLcUnInt_H},//PE的PCS先传递的是低位再传高位
		{130, TpyeLcUnInt_L},

		{131, TpyeLcInt_H},
		{132, TpyeLcInt_L},
		{133, TpyeLcInt_H},
		{134, TpyeLcInt_L},

		{135, TpyeLcUnInt_H},
		{136, TpyeLcUnInt_L},
		{137, TpyeLcUnInt_H},
		{138, TpyeLcUnInt_L},

		{139, TpyeLcUnInt_H},
		{140, TpyeLcUnInt_L},
		{141, TpyeLcUnInt_H},
		{142, TpyeLcUnInt_L},
		{143, TpyeLcUnInt_H},
		{144, TpyeLcUnInt_L},
		{145, TpyeLcUnInt_H},
		{146, TpyeLcUnInt_L},
		{147, TpyeLcUnInt_H},
		{148, TpyeLcUnInt_L},
		{149, TpyeLcUnInt_H},
		{150, TpyeLcUnInt_L},
		{151, TpyeLcUnInt_H},
		{152, TpyeLcUnInt_L},


		{161, TpyeLcUnInt_H},
		{162, TpyeLcUnInt_L},
		{163, TpyeLcUnInt_H},
		{164, TpyeLcUnInt_L},
		{165, TpyeLcUnInt_H},
		{166, TpyeLcUnInt_L},
		{167, TpyeLcUnInt_H},
		{168, TpyeLcUnInt_L},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st pcsModelHoldIsNotU16Regs[] =
	{
		{12262, TpyeLcShort},
		{12263, TpyeLcShort},
		{12264, TpyeLcShort},
		{12265, TpyeLcShort},
		{12266, TpyeLcShort},
		{12267, TpyeLcShort},
		{12268, TpyeLcShort},
		{12269, TpyeLcShort},
		{12270, TpyeLcShort},
		{12271, TpyeLcShort},
		{12272, TpyeLcShort},
		{12279, TpyeLcShort},
		{12280, TpyeLcShort},
		{12281, TpyeLcShort},
		{12282, TpyeLcShort},
		{12284, TpyeLcShort},
		{12290, TpyeLcShort},
		{12291, TpyeLcShort},
		{12292, TpyeLcShort},
		{12371, TpyeLcShort},
		{12373, TpyeLcShort},
		{12375, TpyeLcShort},
		{12377, TpyeLcShort},
		{12379, TpyeLcShort},
		{12381, TpyeLcShort},
		{12383, TpyeLcShort},
		{12385, TpyeLcShort},
		{12386, TpyeLcShort},
		{12388, TpyeLcShort},
		{12390, TpyeLcShort},
		{12392, TpyeLcShort},
		{12393, TpyeLcShort},
		{12394, TpyeLcShort},
		{12395, TpyeLcShort},
		{12400, TpyeLcShort},
		{12401, TpyeLcShort},
		{12406, TpyeLcShort},
		{12407, TpyeLcShort},
		{12408, TpyeLcShort},
		{12409, TpyeLcShort},
		{12410, TpyeLcShort},
		{12441, TpyeLcShort},
		{12443, TpyeLcShort},
		{12445, TpyeLcShort},
		{12447, TpyeLcShort},
		{12449, TpyeLcShort},
		{12451, TpyeLcShort},
		{12453, TpyeLcShort},
		{12455, TpyeLcShort},
		{12457, TpyeLcShort},
		{12459, TpyeLcShort},
		{12461, TpyeLcShort},
		{12481, TpyeLcShort},
		{12483, TpyeLcShort},
		{12485, TpyeLcShort},
		{12487, TpyeLcShort},
		{12489, TpyeLcShort},
		{12491, TpyeLcShort},
		{12493, TpyeLcShort},
		{12495, TpyeLcShort},
		{12497, TpyeLcShort},
		{12499, TpyeLcShort},
		{12501, TpyeLcShort},
};
const TableAddressStruct pcsModelTableHoldAddr[] =
	{
		{12000, 12501},
};
// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st pcsModelInputIsNotU16Regs[] =
	{
		{2664, TpyeLcUnInt_H},
		{2665, TpyeLcUnInt_L},
		{2666, TpyeLcUnInt_H},
		{2667, TpyeLcUnInt_L},
		{2668, TpyeLcUnInt_H},
		{2669, TpyeLcUnInt_L},
		{2670, TpyeLcUnInt_H},
		{2671, TpyeLcUnInt_L},
		{2672, TpyeLcUnInt_H},
		{2673, TpyeLcUnInt_L},
		{2674, TpyeLcUnInt_H},
		{2675, TpyeLcUnInt_L},
		{2676, TpyeLcUnInt_H},
		{2677, TpyeLcUnInt_L},
		{2678, TpyeLcUnInt_H},
		{2679, TpyeLcUnInt_L},
		{2680, TpyeLcUnInt_H},
		{2681, TpyeLcUnInt_L},
		{2682, TpyeLcUnInt_H},
		{2683, TpyeLcUnInt_L},
		{2684, TpyeLcUnInt_H},
		{2685, TpyeLcUnInt_L},
		{2686, TpyeLcUnInt_H},
		{2687, TpyeLcUnInt_L},

		{2710, TpyeLcShort},
		{2711, TpyeLcShort},
		{2712, TpyeLcShort},
		{2714, TpyeLcShort},
		{2715, TpyeLcShort},

		{2716, TpyeLcShort},
		{2717, TpyeLcShort},
		{2718, TpyeLcShort},
		{2719, TpyeLcShort},
		{2720, TpyeLcShort},
		{2722, TpyeLcShort},
		{2736, TpyeLcShort},
		{2741, TpyeLcShort},
		{2743, TpyeLcShort},
		{2803, TpyeLcShort},
		{2806, TpyeLcShort},
		
		{2815, TpyeLcShort},
		{2816, TpyeLcShort},
		{2817, TpyeLcShort},
		{2818, TpyeLcShort},
		{2819, TpyeLcShort},

		{2833, TpyeLcShort},
		{2834, TpyeLcShort},
		{2835, TpyeLcShort},

		{2836, TpyeLcShort},
		{2837, TpyeLcShort},
		{2838, TpyeLcShort},
		{2839, TpyeLcShort},
		{2840, TpyeLcShort},
		{2841, TpyeLcShort},
		
		{2842, TpyeLcShort},
		{2843, TpyeLcShort},
		{2844, TpyeLcShort},
		{2845, TpyeLcShort},
		{2846, TpyeLcShort},
		{2847, TpyeLcShort},
		{2848, TpyeLcShort},
		{2849, TpyeLcShort},
		{2850, TpyeLcShort},
		{2851, TpyeLcShort},
		{2852, TpyeLcShort},
		{2853, TpyeLcShort},
		{2854, TpyeLcShort},
		{2855, TpyeLcShort},
		{2856, TpyeLcShort},
		{2857, TpyeLcShort},
		{2858, TpyeLcShort},
		{2859, TpyeLcShort},
		{2860, TpyeLcShort},
		{2861, TpyeLcShort},
		{2862, TpyeLcShort},
		{2863, TpyeLcShort},
		{2864, TpyeLcShort},
		{2865, TpyeLcShort},
		{2866, TpyeLcShort},
		{2867, TpyeLcShort},
		{2868, TpyeLcShort},
		{2869, TpyeLcShort},
		{2870, TpyeLcShort},
		{2871, TpyeLcShort},
		{2872, TpyeLcShort},
		{2873, TpyeLcShort},
		{2874, TpyeLcShort},
		{2875, TpyeLcShort},
		// {2847, TpyeLcUnShort},//33
};
const TableAddressStruct pcsModelTableInputAddr[] =
	{
		{2600, 2875},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st pcsGroupHoldIsNotU16Regs[] =
	{
		{27000, TpyeLcShort},
		{27001, TpyeLcShort},
		{27002, TpyeLcShort},
};
const TableAddressStruct pcsGroupTableHoldAddr[] =
	{
		{27000, 27050},

		{27103, 27119},

};
// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st pcsGroupInputIsNotU16Regs[] =
	{
		{17000, TpyeLcUnShort},
		{17001, TpyeLcUnShort},
		{17002, TpyeLcUnShort},
		{17003, TpyeLcUnShort},
		{17004, TpyeLcUnShort},
		{17005, TpyeLcUnShort},
		{17006, TpyeLcUnShort},
		{17007, TpyeLcUnShort},
		{17008, TpyeLcUnShort},
		{17009, TpyeLcUnShort},
		{17010, TpyeLcUnShort},
		{17011, TpyeLcUnShort},
		{17012, TpyeLcUnShort},
		{17013, TpyeLcUnShort},
		{17014, TpyeLcUnShort},
		{17015, TpyeLcUnShort},
		{17016, TpyeLcUnShort},
		{17017, TpyeLcUnShort},
		{17018, TpyeLcUnShort},
		{17019, TpyeLcUnShort},
		{17020, TpyeLcUnShort},


		{17021, TpyeLcUnShort},
		{17022, TpyeLcUnShort},
		{17023, TpyeLcUnShort},
		{17024, TpyeLcUnShort},
		{17025, TpyeLcUnShort},
		{17026, TpyeLcUnShort},
		{17027, TpyeLcUnShort},
		{17028, TpyeLcUnShort},
		{17029, TpyeLcUnShort},
		{17030, TpyeLcUnShort},
		{17031, TpyeLcUnShort},
		{17032, TpyeLcUnShort},
		{17033, TpyeLcUnShort},
		{17034, TpyeLcUnShort},
		{17035, TpyeLcUnShort},
		{17036, TpyeLcUnShort},
		{17037, TpyeLcUnShort},
		{17038, TpyeLcUnShort},
		{17039, TpyeLcUnShort},
		{17040, TpyeLcUnShort},
		{17041, TpyeLcUnShort},



		{17042, TpyeLcUnShort},
		{17043, TpyeLcUnShort},
		{17044, TpyeLcUnShort},
		{17045, TpyeLcUnShort},
		{17046, TpyeLcUnShort},
		{17047, TpyeLcUnShort},
		{17048, TpyeLcUnShort},
		{17049, TpyeLcUnShort},
		{17050, TpyeLcShort},
		{17051, TpyeLcShort},
		{17052, TpyeLcShort},
		{17053, TpyeLcUnShort},
		{17054, TpyeLcShort},
		{17055, TpyeLcShort},
		{17056, TpyeLcUnShort},
		{17057, TpyeLcUnShort},
		{17058, TpyeLcUnShort},
		{17059, TpyeLcUnShort},
		{17060, TpyeLcUnShort},
		{17061, TpyeLcUnShort},
		{17062, TpyeLcUnShort},



		{17063, TpyeLcUnShort},
		{17064, TpyeLcUnShort},
		{17065, TpyeLcUnShort},
		{17066, TpyeLcUnShort},
		{17067, TpyeLcUnShort},
		{17068, TpyeLcUnShort},
		{17069, TpyeLcUnShort},
		{17070, TpyeLcUnShort},
		{17071, TpyeLcUnShort},
		{17072, TpyeLcUnShort},
		{17073, TpyeLcUnShort},
		{17074, TpyeLcUnShort},
		{17075, TpyeLcUnShort},
		{17076, TpyeLcUnShort},
		{17077, TpyeLcUnShort},
		{17078, TpyeLcUnShort},
		{17079, TpyeLcUnShort},
		{17080, TpyeLcUnShort},
		{17081, TpyeLcUnShort},
		{17082, TpyeLcUnShort},
		{17083, TpyeLcUnShort},
		{17084, TpyeLcUnShort},
		{17085, TpyeLcUnShort},
		{17086, TpyeLcUnShort},
		{17087, TpyeLcUnShort},
		{17088, TpyeLcUnShort},
		{17089, TpyeLcUnShort},
		{17090, TpyeLcUnShort},
		{17091, TpyeLcUnShort}
};
const TableAddressStruct pcsGroupTableInputAddr[] =
	{
		{17000, 17091},
};

const TableAddressStruct cell_tempTableInputAddr[] =
	{
		{640, 1151},
};

const TableAddressStruct cell_volTableInputAddr[] =
	{
		{128, 639},
};

const TableAddressStruct cell_poleTableInputAddr[] =
	{
		{0, 63},
		{64, 127},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st bmsInputIsNotU16Regs[] =
	{
		{38000, TpyeXieShort},
		{38001, TpyeXieInt_H},
		{38002, TpyeXieInt_L},
		{38015, TpyeXieShort},
		{38019, TpyeXieShort},
		{38020, TpyeXieShort},
		{38024, TpyeXieShort},
		{38028, TpyeXieShort},
		{38029, TpyeXieShort},
};

const TableAddressStruct bmsTableHoldAddr[] =
	{
		{35001, 35039},
		
};

const TableAddressStruct bmsTableInputAddr[] =
	{
		{38000, 38074},
};

const TableAddressStruct rackTableInputAddr[] =
	{
		{31000, 31153},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st rackInputIsNotU16Regs[] =
	{
		{31010, TpyeXieShort},
		{31013, TpyeXieShort},
		{31031, TpyeXieShort},
		{31032, TpyeXieShort},
		{31033, TpyeXieShort},
		{31034, TpyeXieShort},
		{31035, TpyeXieShort},
		{31036, TpyeXieShort},
		{31037, TpyeXieShort},

		{31042, TpyeXieShort},
		{31043, TpyeXieShort},
		{31044, TpyeXieShort},
		{31045, TpyeXieShort},	
		{31046, TpyeXieShort},
		{31047, TpyeXieShort},	

		{31065, TpyeXieShort},
		{31067, TpyeXieShort},	

		{31071, TpyeXieShort},
		{31072, TpyeXieShort},	
		{31073, TpyeXieShort},
		{31074, TpyeXieShort},	
		{31075, TpyeXieShort},
		{31081, TpyeXieShort},
		{31083, TpyeXieShort},
		{31085, TpyeXieShort},
		{31087, TpyeXieShort},
		{31088, TpyeXieShort},
		{31089, TpyeXieShort},

		{31107, TpyeXieShort},
		{31109, TpyeXieShort},
		{31111, TpyeXieShort},
		{31113, TpyeXieShort},


};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st meterInputIsNotU16Regs[] =
	{
		{25300, TpyeLcFloat_H},
		{25301, TpyeLcFloat_L},
		{25302, TpyeLcFloat_H},
		{25303, TpyeLcFloat_L},
		{25304, TpyeLcFloat_H},
		{25305, TpyeLcFloat_L},
		{25306, TpyeLcFloat_H},
		{25307, TpyeLcFloat_L},
		{25308, TpyeLcFloat_H},
		{25309, TpyeLcFloat_L},
		{25310, TpyeLcFloat_H},
		{25311, TpyeLcFloat_L},
		{25312, TpyeLcFloat_H},
		{25313, TpyeLcFloat_L},
		{25314, TpyeLcFloat_H},
		{25315, TpyeLcFloat_L},
		{25316, TpyeLcFloat_H},
		{25317, TpyeLcFloat_L},

		{25318, TpyeLcFloat_H},
		{25319, TpyeLcFloat_L},
		{25320, TpyeLcFloat_H},
		{25321, TpyeLcFloat_L},
		{25322, TpyeLcFloat_H},
		{25323, TpyeLcFloat_L},
		{25324, TpyeLcFloat_H},
		{25325, TpyeLcFloat_L},
		{25326, TpyeLcFloat_H},
		{25327, TpyeLcFloat_L},

		{25328, TpyeLcFloat_H},
		{25329, TpyeLcFloat_L},
		{25330, TpyeLcFloat_H},
		{25331, TpyeLcFloat_L},
		{25332, TpyeLcFloat_H},
		{25333, TpyeLcFloat_L},
		{25334, TpyeLcFloat_H},
		{25335, TpyeLcFloat_L},
		{25336, TpyeLcFloat_H},
		{25337, TpyeLcFloat_L},

		{25338, TpyeLcFloat_H},
		{25339, TpyeLcFloat_L},
		{25340, TpyeLcFloat_H},
		{25341, TpyeLcFloat_L},
		{25342, TpyeLcFloat_H},
		{25343, TpyeLcFloat_L},
		{25344, TpyeLcFloat_H},
		{25345, TpyeLcFloat_L},
		{25346, TpyeLcFloat_H},
		{25347, TpyeLcFloat_L},

		{25348, TpyeLcFloat_H},
		{25349, TpyeLcFloat_L},
		{25350, TpyeLcFloat_H},
		{25351, TpyeLcFloat_L},
		{25352, TpyeLcFloat_H},
		{25353, TpyeLcFloat_L},
		{25354, TpyeLcFloat_H},
		{25355, TpyeLcFloat_L},
		{25356, TpyeLcFloat_H},
		{25357, TpyeLcFloat_L},

		{25358, TpyeLcFloat_H},
		{25359, TpyeLcFloat_L},
		{25360, TpyeLcFloat_H},
		{25361, TpyeLcFloat_L},
		{25362, TpyeLcFloat_H},
		{25363, TpyeLcFloat_L},
		{25364, TpyeLcFloat_H},
		{25365, TpyeLcFloat_L},
		{25366, TpyeLcFloat_H},
		{25367, TpyeLcFloat_L},

		{25368, TpyeLcFloat_H},
		{25369, TpyeLcFloat_L},
		{25370, TpyeLcFloat_H},
		{25371, TpyeLcFloat_L},
		{25372, TpyeLcFloat_H},
		{25373, TpyeLcFloat_L},
		// {25374, TpyeLcFloat_H},
		// {25375, TpyeLcFloat_L},

};
const TableAddressStruct meterTableInputAddr[] =
	{
		{25300, 25373},
};

const TableAddressStruct sydyTableHoldAddr[] =
	{
		{33000, 33007},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st sydyInputIsNotU16Regs[] =
	{
		{26000, TpyeLcFloat_H},
		{26001, TpyeLcFloat_L},
		{26002, TpyeLcFloat_H},
		{26003, TpyeLcFloat_L},
		{26004, TpyeLcFloat_H},
		{26005, TpyeLcFloat_L},
		{26006, TpyeLcFloat_H},
		{26007, TpyeLcFloat_L},
		{26008, TpyeLcFloat_H},
		{26009, TpyeLcFloat_L},
		{26010, TpyeLcFloat_H},
		{26011, TpyeLcFloat_L},
		{26012, TpyeLcFloat_H},
		{26013, TpyeLcFloat_L},
		{26014, TpyeLcFloat_H},
		{26015, TpyeLcFloat_L},
		{26016, TpyeLcFloat_H},
		{26017, TpyeLcFloat_L},

		{26018, TpyeLcFloat_H},
		{26019, TpyeLcFloat_L},
		{26020, TpyeLcFloat_H},
		{26021, TpyeLcFloat_L},
		{26022, TpyeLcFloat_H},
		{26023, TpyeLcFloat_L},
		{26024, TpyeLcFloat_H},
		{26025, TpyeLcFloat_L},
		{26026, TpyeLcFloat_H},
		{26027, TpyeLcFloat_L},

		{26028, TpyeLcFloat_H},
		{26029, TpyeLcFloat_L},
		{26030, TpyeLcFloat_H},
		{26031, TpyeLcFloat_L},
		{26032, TpyeLcFloat_H},
		{26033, TpyeLcFloat_L},
		{26034, TpyeLcFloat_H},
		{26035, TpyeLcFloat_L},

};
const TableAddressStruct sydyTableInputAddr[] =
	{
		{26000, 26034},
		{26100, 26107},
};

// 点表中非16位无符号整型的点位作特殊处理
const reg_type_st auxInputIsNotU16Regs[] =
	{
		{25000, TpyeLcFloat_H},
		{25001, TpyeLcFloat_L},
		{25002, TpyeLcFloat_H},
		{25003, TpyeLcFloat_L},
		{25004, TpyeLcFloat_H},
		{25005, TpyeLcFloat_L},
		{25006, TpyeLcFloat_H},
		{25007, TpyeLcFloat_L},

		{25300, TpyeLcFloat_H},
		{25301, TpyeLcFloat_L},
		{25302, TpyeLcFloat_H},
		{25303, TpyeLcFloat_L},
		{25304, TpyeLcFloat_H},
		{25305, TpyeLcFloat_L},
		{25306, TpyeLcFloat_H},
		{25307, TpyeLcFloat_L},
		{25308, TpyeLcFloat_H},
		{25309, TpyeLcFloat_L},
		{25310, TpyeLcFloat_H},
		{25311, TpyeLcFloat_L},
		{25312, TpyeLcFloat_H},
		{25313, TpyeLcFloat_L},
		{25314, TpyeLcFloat_H},
		{25315, TpyeLcFloat_L},
		{25316, TpyeLcFloat_H},
		{25317, TpyeLcFloat_L},
		{25318, TpyeLcFloat_H},
		{25319, TpyeLcFloat_L},
		{25320, TpyeLcFloat_H},
		{25321, TpyeLcFloat_L},
		{25322, TpyeLcFloat_H},
		{25323, TpyeLcFloat_L},
		{25324, TpyeLcFloat_H},
		{25325, TpyeLcFloat_L},
		{25326, TpyeLcFloat_H},
		{25327, TpyeLcFloat_L},
		{25328, TpyeLcFloat_H},
		{25329, TpyeLcFloat_L},
		{25330, TpyeLcFloat_H},
		{25331, TpyeLcFloat_L},
		{25332, TpyeLcFloat_H},
		{25333, TpyeLcFloat_L},
		{25334, TpyeLcFloat_H},
		{25335, TpyeLcFloat_L},
		{25336, TpyeLcFloat_H},
		{25337, TpyeLcFloat_L},
		{25338, TpyeLcFloat_H},
		{25339, TpyeLcFloat_L},
		{25340, TpyeLcFloat_H},
		{25341, TpyeLcFloat_L},
		{25342, TpyeLcFloat_H},
		{25343, TpyeLcFloat_L},
		{25344, TpyeLcFloat_H},
		{25345, TpyeLcFloat_L},
		{25346, TpyeLcFloat_H},
		{25347, TpyeLcFloat_L},
		{25348, TpyeLcFloat_H},
		{25349, TpyeLcFloat_L},
		{25350, TpyeLcFloat_H},
		{25351, TpyeLcFloat_L},
		{25352, TpyeLcFloat_H},
		{25353, TpyeLcFloat_L},
		{25354, TpyeLcFloat_H},
		{25355, TpyeLcFloat_L},
		{25356, TpyeLcFloat_H},
		{25357, TpyeLcFloat_L},
		{25358, TpyeLcFloat_H},
		{25359, TpyeLcFloat_L},
		{25360, TpyeLcFloat_H},
		{25361, TpyeLcFloat_L},
		{25362, TpyeLcFloat_H},
		{25363, TpyeLcFloat_L},
		{25364, TpyeLcFloat_H},
		{25365, TpyeLcFloat_L},
		{25366, TpyeLcFloat_H},
		{25367, TpyeLcFloat_L},
		{25368, TpyeLcFloat_H},
		{25369, TpyeLcFloat_L},
		{25370, TpyeLcFloat_H},
		{25371, TpyeLcFloat_L},
		{25372, TpyeLcFloat_H},
		{25373, TpyeLcFloat_L},


		{25800, TpyeLcFloat_H},
		{25801, TpyeLcFloat_L},
		{25802, TpyeLcFloat_H},
		{25803, TpyeLcFloat_L},
		{25804, TpyeLcFloat_H},
		{25805, TpyeLcFloat_L},
		{25806, TpyeLcFloat_H},
		{25807, TpyeLcFloat_L},
		{25808, TpyeLcFloat_H},
		{25809, TpyeLcFloat_L},
		{25810, TpyeLcFloat_H},
		{25811, TpyeLcFloat_L},
		{25812, TpyeLcFloat_H},
		{25813, TpyeLcFloat_L},
		{25814, TpyeLcFloat_H},
		{25815, TpyeLcFloat_L},
		{25816, TpyeLcFloat_H},
		{25817, TpyeLcFloat_L},
		{25818, TpyeLcFloat_H},
		{25819, TpyeLcFloat_L},
		{25820, TpyeLcFloat_H},
		{25821, TpyeLcFloat_L},

		{27121, TpyeLcUnInt_H},
		{27122, TpyeLcUnInt_L},


		{27450, TpyeLcFloat_H},
		{27451, TpyeLcFloat_L},
		{27452, TpyeLcFloat_H},
		{27453, TpyeLcFloat_L},
		{27454, TpyeLcFloat_H},
		{27455, TpyeLcFloat_L},
		{27456, TpyeLcFloat_H},
		{27457, TpyeLcFloat_L},

		{27458, TpyeLcFloat_H},
		{27459, TpyeLcFloat_L},
		{27460, TpyeLcFloat_H},
		{27461, TpyeLcFloat_L},
		{27462, TpyeLcFloat_H},
		{27463, TpyeLcFloat_L},
		{27464, TpyeLcFloat_H},
		{27465, TpyeLcFloat_L},
		{27466, TpyeLcFloat_H},
		{27467, TpyeLcFloat_L},

		{27468, TpyeLcFloat_H},
		{27469, TpyeLcFloat_L},
		{27470, TpyeLcFloat_H},
		{27471, TpyeLcFloat_L},
		{27472, TpyeLcFloat_H},
		{27473, TpyeLcFloat_L},
		{27474, TpyeLcFloat_H},
		{27475, TpyeLcFloat_L},
		{27476, TpyeLcFloat_H},
		{27477, TpyeLcFloat_L},
		{27478, TpyeLcFloat_H},
		{27479, TpyeLcFloat_L},
		{27480, TpyeLcFloat_H},
		{27481, TpyeLcFloat_L},
		{27482, TpyeLcFloat_H},
		{27483, TpyeLcFloat_L},



};
const TableAddressStruct auxTableInputAddr[] =
	{
		{25000, 25015},//变压器
		{25800, 25821},//高压综合保护单元

		{27100, 27133},//UPS
		{27300, 27418},//测控遥信

		{27450, 27483},//测控遥测

};



const TableAddressStruct faultTableInputAddr[] =
	{
		{107, 107},//emu 1
 
		
	    {2623, 2626}, //主1PCS
		{2631, 2634}, 
		{2650, 2660}, 
		{2752, 2763}, 

		{2923, 2926}, //从1PCS
		{2931, 2934}, 
		{2950, 2960}, 
		{3052, 3063}, 
	
	    {3223, 3226}, //主2PCS
		{3231, 3234}, 
		{3250, 3260}, 
		{3352, 3363}, 

		{3523, 3526}, //从2PCS
		{3531, 3534}, 
		{3550, 3560}, 
		{3652, 3663}, 


		// {17066, 17072},//pcsGroup 1
		// {17366, 17372},//pcsGroup 2


		{27129, 27132},//MV 
		{27300, 27304},
		{27355, 27358},

		{38039+0*200, 38039+0*200},//BMS 1
		{38039+1*200, 38039+1*200},//BMS 2
		{38039+2*200, 38039+2*200},//BMS 3
		{38039+3*200, 38039+3*200},//BMS 4
		{38039+4*200, 38039+4*200},//BMS 5
		{38039+5*200, 38039+5*200},//BMS 6
		{38039+6*200, 38039+6*200},//BMS 7
		{38039+7*200, 38039+7*200},//BMS 8

		// {28039, 28051},//BMS 1
		// {28127, 28136},
		// {31114, 31121},
		// {31130, 31137},


		// {28039+1*200, 28051+1*200},//BMS 2
		// {28127+1*200, 28136+1*200},
		// {31114+1*200, 31121+1*200},
		// {31130+1*200, 31137+1*200},


		// {28039+2*200, 28051+2*200},//BMS 3
		// {28127+2*200, 28136+2*200},
		// {31114+2*200, 31121+2*200},
		// {31130+2*200, 31137+2*200},


		// {28039+3*200, 28051+3*200},//BMS 4
		// {28127+3*200, 28136+3*200},
		// {31114+3*200, 31121+3*200},
		// {31130+3*200, 31137+3*200},


		// {28039+4*200, 28051+4*200},//BMS 5
		// {28127+4*200, 28136+4*200},
		// {31114+4*200, 31121+4*200},
		// {31130+4*200, 31137+4*200},

		
		// {28039+5*200, 28051+5*200},//BMS 6
		// {28127+5*200, 28136+5*200},
		// {31114+5*200, 31121+5*200},
		// {31130+5*200, 31137+5*200},
		

		// {28039+6*200, 28051+6*200},//BMS 7
		// {28127+6*200, 28136+6*200},
		// {31114+6*200, 31121+6*200},
		// {31130+6*200, 31137+6*200},
	

		// {28039+7*200, 28051+7*200},//BMS 8
		// {28127+7*200, 28136+7*200},
		// {31114+7*200, 31121+7*200},
		// {31130+7*200, 31137+7*200},

};

// 数据库指令字符串
char sqlstr[15000] = {0};

#ifdef USE_DB

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void bms_CreateSqlstr(void)
{
	int num;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	// unsigned char bmsNumIni = sys_cfg->bmsNum;
	// for(int num = 0; num < bmsNumIni; num++)
	// {
	zone = sizeof(bmsTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (uint16_t add = bmsTableInputAddr[z].start; add <= bmsTableInputAddr[z].end; add++)
		{
			type = TpyeXieUnShort;
			for (uint16_t i = 0; i < sizeof(bmsInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (bmsInputIsNotU16Regs[i].RegAdd == add)
				{
					type = bmsInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeXieShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeXieFloat_H:break;
			case TpyeXieFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			case TpyeXieInt_H:break;
			case TpyeXieInt_L:
				sprintf(sqlstrtemp, ",Input%d SMALLINT SIGNED\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	// zone = sizeof(bmsTableHoldAddr) / sizeof(TableAddressStruct);
	// for (int z = 0; z < zone; z++)
	// {
	// 	for (uint16_t add = bmsTableHoldAddr[z].start; add < bmsTableHoldAddr[z].end; add++)
	// 	{
	// 		sprintf(sqlstrtemp, ",Hold%d SMALLINT UNSIGNED\0", add);
	// 		strcat(sqlstr, sqlstrtemp);
	// 	}
	// }

	// }
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void bms_InsertSqlstr(int num)
{
	char sqlstrtemp[200] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	uint16_t offset = 200 * (num);//uint16_t offset = 100 * (num);
	zone = sizeof(bmsTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (uint16_t add = bmsTableInputAddr[z].start; add <= bmsTableInputAddr[z].end; add++)
		{
			type = TpyeXieUnShort;
			for (uint16_t i = 0; i < sizeof(bmsInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (bmsInputIsNotU16Regs[i].RegAdd == add)
				{
					type = bmsInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeXieShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeXieUnInt_H:
				break;
			case TpyeXieUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.D32);
				break;
			case TpyeXieInt_H:
				break;
			case TpyeXieInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.DS32);
				break;				
			case TpyeXieFloat_H:
				break;
			case TpyeXieFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	offset = 300 * (num);//offset = 300 * (num);
	// zone = sizeof(bmsTableHoldAddr) / sizeof(TableAddressStruct);
	// for (int z = 0; z < zone; z++)
	// {
	// 	for (uint16_t add = bmsTableHoldAddr[z].start; add < bmsTableHoldAddr[z].end; add++)
	// 	{
	// 		RegVal.D16 = GET_HOLD(add + offset);
	// 		sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
	// 		strcat(sqlstr, sqlstrtemp);
	// 	}
	// }
}

/**
 * @brief bms_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_bms_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists bms%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	bms_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("Bank mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists bms%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}

	// bzero_all(sqlstr);
	// strcat(sqlstr, "START TRANSACTION;\0");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }
	int bmsNumIni = sys_cfg->bmsNum;
	for (int num = 0; num < bmsNumIni; num++)//修改了这个，bmsNumIni
	{

		bzero_all(sqlstr);
		sprintf(sqlstr, "insert into bms%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
				tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, num);
		bms_InsertSqlstr(num);
		strcat(sqlstr, ");\0");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			printf("sqlstr = %s\n", sqlstr);
			printf("mysql_query failure!\n");
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			printf("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_bms_Table = %s\n", sqlstr);
#endif // DEBUG ISDEBUG_

			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void rack_CreateSqlstr(void)
{
	int  num;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(rackTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{

		for (unsigned short add = rackTableInputAddr[z].start; add <= rackTableInputAddr[z].end; add++)
		{
			type = TpyeXieUnShort;
			for (uint16_t i = 0; i < sizeof(rackInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (rackInputIsNotU16Regs[i].RegAdd == add)
				{
					type = rackInputIsNotU16Regs[i].Type;
					break;
				}
			}

			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeXieShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void rack_InsertSqlstr(uint8_t bms_num, uint8_t Rack_id)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(rackTableInputAddr) / sizeof(TableAddressStruct);
	uint16_t offset = 3000 * (bms_num)+Rack_id*200;//修改了这个
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = rackTableInputAddr[z].start; add <= rackTableInputAddr[z].end; add++)
		{
			type = TpyeXieUnShort;
			for (unsigned short i = 0; i < sizeof(rackInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (rackInputIsNotU16Regs[i].RegAdd == add)
				{
					type = rackInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeXieShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeXieUnInt_H:

				break;
			case TpyeXieUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.D32);
				break;
			case TpyeXieFloat_H:

				break;
			case TpyeXieFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief rack_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_rack_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	uint8_t bms_num;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists rack%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED,Rack SMALLINT UNSIGNED\0");
	rack_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("rack mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists rack%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "START TRANSACTION;\0");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("START TRANSACTION failed!\n");
	}
	for (bms_num = 0; (bms_num < sys_cfg->bmsNum) && (bms_num < MAX_BMS_NUM); bms_num++)//(bms_num = 0; (bms_num < sys_cfg->bmsNum) && (bms_num < MAX_BMS_NUM); bms_num++)
	{
		int NumIni = sys_cfg->bms_cluster[bms_num];
		for (int Rack_id = 0; Rack_id < NumIni; Rack_id++)
		{

			bzero_all(sqlstr);
			sprintf(sqlstr, "insert into rack%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d,%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
					tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, bms_num, Rack_id);
			rack_InsertSqlstr(bms_num, Rack_id);
			strcat(sqlstr, ");\0");
			if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
			{
				printf("sqlstr = %s\n", sqlstr);
				printf("mysql_query failure!\n");
				res1 = 2;
			}
			else
			{
#ifdef ISDEBUG_
				printf("sqlstr = %s\n", sqlstr);
				LOG_INFO("LC_DATA:Insert_rack_Table = %s\n", sqlstr);
#endif
				// printf("mysql_query!\n");
			}
		}
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "COMMIT;");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("COMMIT failed!\n");
	}
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void cell_temp_CreateSqlstr(void)
{
	int  z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned int len_ini = sys_cfg->bms_temp_num[0];
	zone = sizeof(cell_tempTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_tempTableInputAddr[z].start; (add <= cell_tempTableInputAddr[z].end) && (add < cell_tempTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void cell_temp_InsertSqlstr(uint8_t bms_num, uint8_t Rack_id)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned int len_ini = sys_cfg->bms_temp_num[bms_num];
	zone = sizeof(cell_tempTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_tempTableInputAddr[z].start; (add <= cell_tempTableInputAddr[z].end) && (add < cell_tempTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			RegVal.D16 = GET_R_INPUT(1, Rack_id * R_INPUT_SIZE + add);//修改了这里
			sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief cell_temp_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_cell_temp_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	int res, i;
	uint8_t bms_num;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists cell_temp%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED,Rack SMALLINT UNSIGNED\0");
	cell_temp_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("cell_temp mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists cell_temp%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "START TRANSACTION;\0");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("START TRANSACTION failed!\n");
	}
	for (bms_num = 0; (bms_num < sys_cfg->bmsNum) && (bms_num < MAX_BMS_NUM); bms_num++)
	{
		int NumIni = sys_cfg->bms_cluster[bms_num];
		for (int Rack_id = 0; Rack_id < NumIni; Rack_id++)
		{

			bzero_all(sqlstr);
			sprintf(sqlstr, "insert into cell_temp%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d,%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
					tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, bms_num, Rack_id);
			cell_temp_InsertSqlstr(bms_num, Rack_id);
			strcat(sqlstr, ");\0");
			if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
			{
				printf("sqlstr = %s\n", sqlstr);
				printf("mysql_query failure!\n");
				res1 = 2;
			}
			else
			{

#ifdef ISDEBUG_
				printf("sqlstr = %s\n", sqlstr);
				LOG_INFO("LC_DATA:Insert_cell_temp_Table = %s\n", sqlstr);
#endif
				// printf("mysql_query!\n");
			}
		}
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "COMMIT;");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("COMMIT failed!\n");
	}
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void cell_pole_CreateSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned int len_ini = sys_cfg->bms_pole_num[0];
	zone = sizeof(cell_poleTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_poleTableInputAddr[z].start; (add <= cell_poleTableInputAddr[z].end) && (add < cell_poleTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void cell_pole_InsertSqlstr(uint8_t bms_num, uint8_t Rack_id)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned int len_ini = sys_cfg->bms_pole_num[bms_num];
	zone = sizeof(cell_poleTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_poleTableInputAddr[z].start; (add <= cell_poleTableInputAddr[z].end) && (add < cell_poleTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			RegVal.D16 = GET_R_INPUT(1, Rack_id * R_INPUT_SIZE + add);//修改了这个
		
			sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief cell_pole_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_cell_pole_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	int res, i;
	uint8_t bms_num;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists cell_pole%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED,Rack SMALLINT UNSIGNED\0");
	cell_pole_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("cell_pole mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists cell_pole%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "START TRANSACTION;\0");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("START TRANSACTION failed!\n");
	}
	for (bms_num = 0; (bms_num < sys_cfg->bmsNum) && (bms_num < MAX_BMS_NUM); bms_num++)
	{
		int NumIni = sys_cfg->bms_cluster[bms_num];
		for (int Rack_id = 0; Rack_id < NumIni; Rack_id++)
		{

			bzero_all(sqlstr);
			sprintf(sqlstr, "insert into cell_pole%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d,%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
					tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, bms_num, Rack_id);
			cell_pole_InsertSqlstr(bms_num, Rack_id);
			strcat(sqlstr, ");\0");
			if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
			{
				printf("sqlstr = %s\n", sqlstr);
				printf("mysql_query failure!\n");
				res1 = 2;
			}
			else
			{
#ifdef ISDEBUG_
				printf("sqlstr = %s\n", sqlstr);
				LOG_INFO("LC_DATA:Insert_cell_pole_Table = %s\n", sqlstr);
#endif
				// printf("mysql_query!\n");
			}
		}
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "COMMIT;");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("COMMIT failed!\n");
	}
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void pcsModel_CreateSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned char pcsModelNumIni = sys_cfg->pcsModelNum;

	zone = sizeof(pcsModelTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsModelTableInputAddr[z].start; add <= pcsModelTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(pcsModelInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (pcsModelInputIsNotU16Regs[i].RegAdd == add)
				{
					type = pcsModelInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;	
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(pcsModelTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsModelTableHoldAddr[z].start; add < pcsModelTableHoldAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(pcsModelHoldIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (pcsModelHoldIsNotU16Regs[i].RegAdd == add)
				{
					type = pcsModelHoldIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Hold%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Hold%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Hold%d INT\0", add);
				break;	
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Hold%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Hold%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void cell_vol_CreateSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(cell_volTableInputAddr) / sizeof(TableAddressStruct);
	unsigned int len_ini = sys_cfg->bms_vol_num[0];
	for (unsigned int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_volTableInputAddr[z].start; (add <= cell_volTableInputAddr[z].end) && (add < cell_volTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void cell_vol_InsertSqlstr(uint8_t bms_num, uint8_t Rack_id)
{

	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(cell_volTableInputAddr) / sizeof(TableAddressStruct);
	unsigned int len_ini = sys_cfg->bms_vol_num[bms_num];
	for (unsigned int z = 0; z < zone; z++)
	{
		for (unsigned short add = cell_volTableInputAddr[z].start; (add <= cell_volTableInputAddr[z].end) && (add < cell_volTableInputAddr[z].start + len_ini); add++)
		{
			bzero_all(sqlstrtemp);
			RegVal.D16 = GET_R_INPUT(1, Rack_id * R_INPUT_SIZE + add);//修改了这里
			sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief cell_vol_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_cell_vol_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	int res, i;
	uint8_t bms_num;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists cell_vol%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED UNSIGNED,Rack SMALLINT UNSIGNED UNSIGNED\0");
	cell_vol_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("cell_vol mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists cell_vol%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "START TRANSACTION;\0");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("START TRANSACTION failed!\n");
	}
	for (bms_num = 0; (bms_num < sys_cfg->bmsNum) && (bms_num < MAX_BMS_NUM); bms_num++)
	{
		int NumIni = sys_cfg->bms_cluster[bms_num];
		for (int Rack_id = 0; Rack_id < NumIni; Rack_id++)
		{

			bzero_all(sqlstr);
			sprintf(sqlstr, "insert into cell_vol%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d,%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
					tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, bms_num, Rack_id);
			cell_vol_InsertSqlstr(bms_num, Rack_id);
			strcat(sqlstr, ");\0");
			if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
			{
				printf("sqlstr = %s\n", sqlstr);
				printf("mysql_query failure!\n");
				res1 = 2;
			}
			else
			{
#ifdef ISDEBUG_
				printf("sqlstr = %s\n", sqlstr);
				LOG_INFO("LC_DATA:Insert_cell_vol_Table = %s\n", sqlstr);
#endif
				// printf("mysql_query!\n");
			}
		}
	}
	bzero_all(sqlstr);
	strcat(sqlstr, "COMMIT;");
	if (mysql_query(pmysql, sqlstr))
	{
		printf("COMMIT failed!\n");
	}
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void pcsModel_InsertSqlstr(int num)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	uint16_t offset = 300 * (num);
	zone = sizeof(pcsModelTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsModelTableInputAddr[z].start; add <= pcsModelTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (int i = 0; i < sizeof(pcsModelInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (pcsModelInputIsNotU16Regs[i].RegAdd == add)
				{
					type = pcsModelInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:

				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;

			case TpyeLcInt_H:

				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_H:

				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(pcsModelTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsModelTableHoldAddr[z].start; add < pcsModelTableHoldAddr[z].end; add++)
		{
			RegVal.D16 = GET_HOLD(add + offset);
			sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief pcsModel_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_pcsModel_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists pcsmodel%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	pcsModel_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("pcsmodel mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists pcsmodel%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}

	// bzero_all(sqlstr);
	// strcat(sqlstr, "START TRANSACTION;\0");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }
	int pcsModelNumIni = sys_cfg->pcsNum;
	for (int num = 0; num < pcsModelNumIni; num++)
	{

		bzero_all(sqlstr);
		sprintf(sqlstr, "insert into pcsmodel%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
				tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, num);
		pcsModel_InsertSqlstr(num);
		strcat(sqlstr, ");\0");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			printf("sqlstr = %s\n", sqlstr);
			printf("mysql_query failure!\n");
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			printf("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_pcsModel_Table = %s\n", sqlstr);
#endif
			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void pcsGroup_CreateSqlstr(void)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned char pcsGroupNumIni = sys_cfg->sysNum;

	zone = sizeof(pcsGroupTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsGroupTableInputAddr[z].start; add <= pcsGroupTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(pcsGroupInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (pcsGroupInputIsNotU16Regs[i].RegAdd == add)
				{
					type = pcsGroupInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(pcsGroupTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsGroupTableHoldAddr[z].start; add < pcsGroupTableHoldAddr[z].end; add++)
		{
			sprintf(sqlstrtemp, ",Hold%d SMALLINT UNSIGNED\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void pcsGroup_InsertSqlstr(int num)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	uint16_t offset = 300 * (num);
	zone = sizeof(pcsGroupTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsGroupTableInputAddr[z].start; add <= pcsGroupTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(pcsGroupInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (pcsGroupInputIsNotU16Regs[i].RegAdd == add)
				{
					type = pcsGroupInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:

				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcInt_H:

				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_H:

				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(pcsGroupTableHoldAddr) / sizeof(TableAddressStruct);
	for (unsigned short z = 0; z < zone; z++)
	{
		for (unsigned short add = pcsGroupTableHoldAddr[z].start; add < pcsGroupTableHoldAddr[z].end; add++)
		{
			RegVal.D16 = GET_HOLD(add + offset);
			sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief pcsGroup_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_pcsGroup_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists pcsgroup%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	pcsGroup_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("pcsgroup mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists pcsgroup%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "START TRANSACTION;\0");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }
	int pcsGroupNumIni = sys_cfg->sysNum;
	for (int num = 0; num < pcsGroupNumIni; num++)
	{

		bzero_all(sqlstr);
		sprintf(sqlstr, "insert into pcsgroup%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
				tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, num);
		pcsGroup_InsertSqlstr(num);
		strcat(sqlstr, ");\0");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			printf("sqlstr = %s\n", sqlstr);
			printf("mysql_query failure!\n");
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			printf("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_pcsGroup_Table = %s\n", sqlstr);
#endif
			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void meter_CreateSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned char meterNumIni = 1;

	zone = sizeof(meterTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = meterTableInputAddr[z].start; add <= meterTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(meterInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (meterInputIsNotU16Regs[i].RegAdd == add)
				{
					type = meterInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void meter_InsertSqlstr(int num)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	uint16_t offset = 50 * (num);
	zone = sizeof(meterTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = meterTableInputAddr[z].start; add <= meterTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(meterInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (meterInputIsNotU16Regs[i].RegAdd == add)
				{
					type = meterInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:

				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcInt_H:

				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_H:

				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief meter_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_meter_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists meter%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	meter_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("meter mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists meter%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "START TRANSACTION;\0");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }
	int meterNumIni = 1;
	for (int num = 0; num < meterNumIni; num++)
	{

		bzero_all(sqlstr);
		sprintf(sqlstr, "insert into meter%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
				tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, num);
		meter_InsertSqlstr(num);
		strcat(sqlstr, ");\0");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			printf("sqlstr = %s\n", sqlstr);
			printf("mysql_query failure!\n");
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			printf("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_meter_Table = %s\n", sqlstr);
#endif
			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void sydy_CreateSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned char sydyNumIni = sys_cfg->sydyNum;

	zone = sizeof(sydyTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = sydyTableInputAddr[z].start; add <= sydyTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(sydyInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (sydyInputIsNotU16Regs[i].RegAdd == add)
				{
					type = sydyInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(sydyTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = sydyTableHoldAddr[z].start; add < sydyTableHoldAddr[z].end; add++)
		{
			sprintf(sqlstrtemp, ",Hold%d SMALLINT UNSIGNED\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void sydy_InsertSqlstr(int num)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned short offset = 200 * (num);
	zone = sizeof(sydyTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = sydyTableInputAddr[z].start; add <= sydyTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(sydyInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (sydyInputIsNotU16Regs[i].RegAdd == add)
				{
					type = sydyInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:
				fRegVal.D32 = 0;
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcInt_H:
				fRegVal.DS32 = 0;
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_H:
				fRegVal.D32 = 0;
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add + offset);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	offset = 100 * (num);
	zone = sizeof(sydyTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = sydyTableHoldAddr[z].start; add < sydyTableHoldAddr[z].end; add++)
		{
			RegVal.D16 = GET_HOLD(add + offset);
			sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief sydy_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_sydy_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists sydy%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	sydy_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("sydy mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists sydy%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "START TRANSACTION;\0");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }

	int sydyNumIni = sys_cfg->sydyNum;
	for (int num = 0; num < sydyNumIni; num++)
	{

		bzero_all(sqlstr);
		sprintf(sqlstr, "insert into sydy%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
				tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec, num);
		sydy_InsertSqlstr(num);
		strcat(sqlstr, ");\0");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			printf("sqlstr = %s\n", sqlstr);
			printf("mysql_query failure!\n");
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			printf("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_sydy_Table = %s\n", sqlstr);
#endif
			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// strcat(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void mv_CreateSqlstr(void)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(auxTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = auxTableInputAddr[z].start; add <= auxTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(auxInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (auxInputIsNotU16Regs[i].RegAdd == add)
				{
					type = auxInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void mv_InsertSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned short offset = 0;
	zone = sizeof(auxTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = auxTableInputAddr[z].start; add <= auxTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(auxInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (auxInputIsNotU16Regs[i].RegAdd == add)
				{
					type = auxInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:

				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcFloat_H:

				break;
			case TpyeLcInt_H:

				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	
}

/**
 * @brief aux_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_mv_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	int num =0;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists mv%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,Num SMALLINT UNSIGNED\0");
	mv_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("mv mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists mv%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// sprintf(sqlstr, "START TRANSACTION;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }

	bzero_all(sqlstr);
	sprintf(sqlstr, "insert into mv%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d',%d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
			tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec,num);
	mv_InsertSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("mysql_query failure!\n");
		res1 = 2;
	}
	else
	{
#ifdef ISDEBUG_
		printf("sqlstr = %s\n", sqlstr);
		LOG_INFO("LC_DATA:Insert_aux_Table = %s\n", sqlstr);
#endif
		// printf("mysql_query!\n");
	}

	// bzero_all(sqlstr);
	// sprintf(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}


/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void system_CreateSqlstr(void)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(emuTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = emuTableInputAddr[z].start; add <= emuTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(emuInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (emuInputIsNotU16Regs[i].RegAdd == add)
				{
					type = emuInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H: break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(emuTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = emuTableHoldAddr[z].start; add < emuTableHoldAddr[z].end; add++)
		{
			sprintf(sqlstrtemp, ",Hold%d SMALLINT UNSIGNED\0", add);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void system_InsertSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	unsigned short offset = 0;
	zone = sizeof(emuTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = emuTableInputAddr[z].start; add <= emuTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			for (unsigned short i = 0; i < sizeof(emuInputIsNotU16Regs) / sizeof(reg_type_st); i++)
			{
				if (emuInputIsNotU16Regs[i].RegAdd == add)
				{
					type = emuInputIsNotU16Regs[i].Type;
					break;
				}
			}
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			case TpyeLcUnInt_H:

				break;
			case TpyeLcUnInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.D32);
				break;
			case TpyeLcInt_H:

				break;
			case TpyeLcInt_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%d\0", fRegVal.DS32);
				break;
			case TpyeLcFloat_H:

				break;
			case TpyeLcFloat_L:
				fRegVal.D16[0] = GET_INPUT(add + offset);
				fRegVal.D16[1] = GET_INPUT(add - 1 + offset);
				sprintf(sqlstrtemp, ",%f\0", fRegVal.F32);
				break;
			default:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
	zone = sizeof(emuTableHoldAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = emuTableHoldAddr[z].start; add < emuTableHoldAddr[z].end; add++)
		{
			RegVal.D16 = GET_HOLD(add);
			sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief emu_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_system_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists system%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT\0");
	system_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("system mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists system%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// sprintf(sqlstr, "START TRANSACTION;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }

	bzero_all(sqlstr);
	sprintf(sqlstr, "insert into system%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d'\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
			tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec);
	system_InsertSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("mysql_query failure!\n");
		printf("mysql failure: %s\n",mysql_error(pmysql));
		res1 = 2;
	}
	else
	{
#ifdef ISDEBUG_
		printf("sqlstr = %s\n", sqlstr);
		LOG_INFO("LC_DATA:Insert_emu_Table = %s\n", sqlstr);
#endif
		// printf("mysql_query!\n");
	}

	// bzero_all(sqlstr);
	// sprintf(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}




/**
 * @brief 数据库创建指令
 * @param[in] 无
 * @return 无
 */
static void fault_CreateSqlstr(void)
{
	char sqlstrtemp[100] = {0};
	int zone, type;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(faultTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		{

			type = TpyeLcUnShort;

			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				sprintf(sqlstrtemp, ",Input%d SMALLINT\0", add);
				break;
			case TpyeLcUnInt_H:break;
			case TpyeLcUnInt_L:
				sprintf(sqlstrtemp, ",Input%d INT UNSIGNED\0", add);
				break;
			case TpyeLcInt_H:break;
			case TpyeLcInt_L:
				sprintf(sqlstrtemp, ",Input%d INT\0", add);
				break;
			case TpyeLcFloat_H:break;
			case TpyeLcFloat_L:
				sprintf(sqlstrtemp, ",Input%d FLOAT\0", add);
				break;
			default:
				sprintf(sqlstrtemp, ",Input%d SMALLINT UNSIGNED\0", add);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}
/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static void fault_InsertSqlstr(void)
{
	int z;
	char sqlstrtemp[100] = {0};
	int zone, type;
	u16_conv RegVal;
	u32_conv fRegVal;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(faultTableInputAddr) / sizeof(TableAddressStruct);
	for (int z = 0; z < zone; z++)
	{
		for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		{
			type = TpyeLcUnShort;
			bzero_all(sqlstrtemp);
			switch (type)
			{
			case TpyeLcShort:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.DS16);
				break;
			
			default:
				RegVal.D16 = GET_INPUT(add);
				sprintf(sqlstrtemp, ",%d\0", RegVal.D16);
				break;
			}
			strcat(sqlstr, sqlstrtemp);
		}
	}
}

/**
 * @brief 数据库插入指令
 * @param[in] 无
 * @return 无
 */
static int fault_InsertSqlstrAll(void)
{
	int z, res;
	unsigned short i;
	char sqlstrtemp[100] = {0};
	int zone, type;
	unsigned short faultVal[10];
	static unsigned short faultValOld[10];
	u16_conv RegVal;
	unsigned char flag;
	sysPara *sys_cfg = SysConf_GetInfo();
	zone = sizeof(faultTableInputAddr) / sizeof(TableAddressStruct);
	bzero_all(faultVal);
	z = 0;
	flag = 0;
	uint8_t pcsmodel_flag=0;
	uint8_t pcsgroup_flag=0;
	uint8_t system_flag=0;
	uint8_t MV_flag=0;
	uint8_t BMS1_flag=0;
	uint8_t BMS2_flag=0;
	uint8_t BMS3_flag=0;
	uint8_t BMS4_flag=0;
	uint8_t BMS5_flag=0;

	static uint16_t Prev_Input_Val[65535] = {0};
	//system故障总
	for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
	{
		RegVal.D16 = GET_INPUT(add);
					       
        if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
        {
            system_flag = 1;                    // 变化标志
            Prev_Input_Val[add] = RegVal.D16; // 更新历史值
        }
		if (RegVal.D16 != 0)
		{
			flag = 1;
			if (system_flag)
			{
				LOG_INFO("New fault occurred: Input[%d] = %d", add, RegVal.D16);
			}
			break;
		}
	}
	// LOG_INFO("============system_flag: %d================\n", system_flag);
	WriteBit(faultVal[0], z, flag);
	bzero_all(sqlstrtemp);
	sprintf(sqlstrtemp, ",%d\0", faultVal[0]);
	strcat(sqlstr, sqlstrtemp);
	//pcsmodel故障总
	for (z = 1, i = 0; z < 5; z++, i++)
	{
		flag = 0;
		for (int y = 0; y < 4; y++)
		{
			for (unsigned short add = faultTableInputAddr[i * 4 + y + 1].start; add <= faultTableInputAddr[i * 4 + y + 1].end; add++)
			{
				RegVal.D16 = GET_INPUT(add);
				/* 判断是否发生变化 */
        		if (RegVal.D16 != Prev_Input_Val[add])
        		{
        		    pcsmodel_flag = 1;                    // 变化标志
        		    Prev_Input_Val[add] = RegVal.D16; // 更新历史值
        		}
				if (RegVal.D16 != 0)
				{
					flag = 1;
					if (pcsmodel_flag)
					{
						LOG_INFO("New fault occurred: Input[%d] = %d", add, RegVal.D16);
					}
				}
			}
		}
		WriteBit(faultVal[1], i, flag);
	}
	bzero_all(sqlstrtemp);
	sprintf(sqlstrtemp, ",%d\0", faultVal[1]);
	strcat(sqlstr, sqlstrtemp);
   //pcsgroup故障总
	// for (z = 5, i = 0; z < 7; z++, i++)
	// {
	// 	flag = 0;
	// 	for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
	// 	{
	// 		RegVal.D16 = GET_INPUT(add);
						       
	// 		if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
	// 		{
	// 			pcsgroup_flag = 1;                    // 变化标志
	// 			Prev_Input_Val[add] = RegVal.D16; // 更新历史值
	// 		}
	// 		if (RegVal.D16 != 0)
	// 		{
	// 			flag = 1;
				
	// 		}
	// 	}
	// 	WriteBit(faultVal[2], i, flag);
	// }
	// bzero_all(sqlstrtemp);
	// sprintf(sqlstrtemp, ",%d\0", faultVal[2]);
	// strcat(sqlstr, sqlstrtemp);
//MV辅助系统故障总
	for (z = 17; z <= 19; z++)
	{
		for (int add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		{
			RegVal.D16 = GET_INPUT(add);
		if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
			{
				MV_flag = 1;                    // 变化标志
				Prev_Input_Val[add] = RegVal.D16; // 更新历史值
			}
			if (RegVal.D16 != 0)
			{
				faultVal[3] = 1;
				if (MV_flag)
				{
					LOG_INFO("New fault occurred: Input[%d] = %d", add, RegVal.D16);
				}
				break;
			}
		}
		if (faultVal[3] != 0)
		{
			break;
		}
	}
	bzero_all(sqlstrtemp);
	sprintf(sqlstrtemp, ",%d\0", faultVal[3]);
	strcat(sqlstr, sqlstrtemp);
//8个BMS故障总
	// z = 9;
	for (i = 0; i < 8; i++, z++)
	{
		flag = 0;
		for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		{
			RegVal.D16 = GET_INPUT(add);
		   if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
			{
				BMS1_flag = 1;                    // 变化标志
				Prev_Input_Val[add] = RegVal.D16; // 更新历史值
			}
			if (RegVal.D16 != 0)
			{
				flag = 1;
				if (BMS1_flag)
				{
					LOG_INFO("New fault occurred: Input[%d] = %d", add, RegVal.D16);
				}
				break;
			}
		}
		WriteBit(faultVal[4], i, flag);
		// z++;
		// for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		// {
		// 	RegVal.D16 = GET_INPUT(add);
		//    if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
		// 	{
		// 		BMS2_flag = 1;                    // 变化标志
		// 		Prev_Input_Val[add] = RegVal.D16; // 更新历史值
		// 	}
		// 	if (RegVal.D16 != 0)
		// 	{
		// 		flag = 1;
		// 		break;
		// 	}
		// }
		// z++;
		// 		for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		// {
		// 	RegVal.D16 = GET_INPUT(add);
		// 	if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
		// 	{
		// 		BMS3_flag = 1;                    // 变化标志
		// 		Prev_Input_Val[add] = RegVal.D16; // 更新历史值
		// 	}
		// 	if (RegVal.D16 != 0)
		// 	{
		// 		flag = 1;
		// 		break;
		// 	}
		// }
		// z++;
		// for (unsigned short add = faultTableInputAddr[z].start; add <= faultTableInputAddr[z].end; add++)
		// {
		// 	RegVal.D16 = GET_INPUT(add);
		//    if (RegVal.D16 != Prev_Input_Val[add]) /* 判断是否发生变化 */
		// 	{
		// 		BMS4_flag = 1;                    // 变化标志
		// 		Prev_Input_Val[add] = RegVal.D16; // 更新历史值
		// 	}
		// 	if (RegVal.D16 != 0)
		// 	{
		// 		flag = 1;
		// 		break;
		// 	}
		// }
		// z++;

		// WriteBit(faultVal[4], i, flag);
	}
	bzero_all(sqlstrtemp);
	sprintf(sqlstrtemp, ",%d\0", faultVal[4]);
	strcat(sqlstr, sqlstrtemp);

	// 比较两个数组
	if ((pcsmodel_flag == 1)||(pcsgroup_flag==1)||(system_flag==1)||(MV_flag==1)||(BMS1_flag==1)||(BMS2_flag==1)||(BMS3_flag==1)||(BMS4_flag==1)||(BMS5_flag==1))
	{

		// 数组内容存在差异
		res = 1;
	 	pcsmodel_flag=0;
		pcsgroup_flag=0;
		system_flag=0;
		MV_flag=0;
		BMS1_flag=0;
		BMS2_flag=0;
	 	BMS3_flag=0;
	 	BMS4_flag=0;
	 	BMS5_flag=0;
		LOG_INFO("===========================\n");
		
	}
	else
	{
		// 数组内容完全相同
		res = 0;
	}
	memcpy(faultValOld, faultVal, sizeof(faultVal));
	return res;
}

/**
 * @brief fault_Table(插入数据库)
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static int Insert_fault_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;
	uint16_t Index;
	static int faildnum = 0;
	int res1 = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	// 数据库更新操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "create table if not exists fault%04d%02d%02d (\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
	strcat(sqlstr, "id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,Time TEXT,system SMALLINT UNSIGNED,pcsmodel SMALLINT UNSIGNED,mv SMALLINT UNSIGNED,bms SMALLINT UNSIGNED\0");
	fault_CreateSqlstr();
	strcat(sqlstr, ");\0");
	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		LOG_INFO("sqlstr = %s\n", sqlstr);
		LOG_INFO("fault mysql_query creat failure!\n");
		if (faildnum++ > 10)
		{
			faildnum = 0;
			bzero_all(sqlstr);
			sprintf(sqlstr, "drop table if exists fault%04d%02d%02d\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday);
			mysql_query(pmysql, sqlstr);
		}
		return 1;
	}
	// sprintf(sqlstr, "START TRANSACTION;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("START TRANSACTION failed!\n");

	// }

	bzero_all(sqlstr);
	sprintf(sqlstr, "insert into fault%04d%02d%02d values(null,'%04d-%02d-%02dT%02d:%02d:%02d'\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday,
			tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, tm_m.tm_hour, tm_m.tm_min, tm_m.tm_sec);
	res = fault_InsertSqlstrAll();
	fault_InsertSqlstr();
	strcat(sqlstr, ");\0");
	if (1 == res)
	{
		LOG_INFO("=======new fault record=====\n");
		if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
		{
			LOG_INFO("sqlstr = %s\n", sqlstr);
			LOG_INFO("mysql_query failure: %s\n", mysql_error(pmysql));
			res1 = 2;
		}
		else
		{
#ifdef ISDEBUG_
			LOG_INFO("sqlstr = %s\n", sqlstr);
			LOG_INFO("LC_DATA:Insert_fault_Table = %s\n", sqlstr);
#endif
			// printf("mysql_query!\n");
		}
	}
	// bzero_all(sqlstr);
	// sprintf(sqlstr, "COMMIT;");
	// if (mysql_query(pmysql, sqlstr)) {
	// 	printf("COMMIT failed!\n");
	// }
	// usleep(100 * 1000);
	return res1;
}

/**
 * @brief 删除过期表
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static void Del_Expire_Table(MYSQL *pmysql)
{
	MYSQL_RES *my_res;
	MYSQL_ROW my_row;
	MYSQL_FIELD *my_field;
	sysPara *sys_cfg = SysConf_GetInfo();
	char sqlstrtemp[100] = {0};
	int res, i;
	int rows;
	int cols;

	long long del_time;
	static char is_done = 0;
	// if((tm_m.tm_hour%10==1)&&(tm_m.tm_min%57==0)&&(is_done ==0))
	if (tm_m.tm_min % 20 == 0)
	{
		is_done = 1;

		bzero_all(sqlstrtemp);
		bzero_all(sqlstr);
		sprintf(sqlstr, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'log_db' AND CREATE_TIME < DATE_SUB('%04d-%02d-%02d', INTERVAL %d DAY);\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, sys_cfg->dbHoldDays);

		// sprintf(sqlstr, "select * from Name_Table where DATE_SUB('%04d-%02d-%02d', INTERVAL %d DAY) > date(Time);\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, sys_cfg->dbHoldDays);
		printf("sqlstr = %s\n", sqlstr);
		res = mysql_query(pmysql, sqlstr);
		my_res = mysql_store_result(pmysql);
		// cols = mysql_num_fields(my_res);
		rows = mysql_num_rows(my_res);
		// my_field = mysql_fetch_fields(my_res);
		printf("rows == %d\t", rows);
		if (rows > 0)
		{
			// for (i = 0; i < cols; i++)
			// {
			// 	printf("%s\t", my_field[i].name);
			// }
			printf("\n-------------------------------------\n");
			while (1) // 查看数据表所有信息
			{
				my_row = mysql_fetch_row(my_res);
				if (NULL == my_row)
					break;
				if (my_row[0] == NULL)
					printf("NULL\t");
				else
				{
					printf("%s\t", (char *)my_row[0]);
					bzero_all(sqlstr);
					sprintf(sqlstr, "drop table if exists %s\0", (char *)my_row[0]);
					// mysql_query(pmysql, sqlstr);
					if (mysql_query(pmysql, sqlstr))
					{
						fprintf(stderr, "Failed to delete %s: %s\n",
								my_row[0], mysql_error(pmysql));
						// 可选：记录失败表名到日志文件
					}
					printf(sqlstr);
					usleep(100 * 1000);
				}
				printf("\n");
			}
			mysql_free_result(my_res);
			// usleep(300 * 1000);
			// bzero_all(sqlstr);
			// sprintf(sqlstr, "delete from Name_Table where DATE_SUB('%04d-%02d-%02d', INTERVAL %d DAY) > date(Time);\0", tm_m.tm_year, tm_m.tm_mon, tm_m.tm_mday, sys_cfg->dbHoldDays);
			// res = mysql_query(pmysql, sqlstr);
		}
		else
		{
			mysql_free_result(my_res);
		}
		usleep(10 * 1000);
	}
	// else
	// {
	// 	is_done = 0;
	// }
}
/**
 * @brief 建库
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
static void Creat_Database(MYSQL *pmysql)
{
	char sqlstrtemp[100] = {0};
	int res, i;
	int res1 = 0;

	// 数据库新增操作
	bzero_all(sqlstr);
	sprintf(sqlstr, "CREATE DATABASE IF NOT EXISTS log_db;\0");

	if (mysql_query(pmysql, sqlstr) != 0) // 插入一条信息
	{
		printf("sqlstr = %s\n", sqlstr);
		printf("log_db mysql_query creat failure!\n");

		return 1;
	}
	else
	{
		// printf("mysql_query creat!\n");
	}
}

/**
 * @brief 处理数据存储到数据库
 * @param[in] 无
 * @return 返回结果 0 为 正常
 */
int Deal_database(void)
{
	int result;
	char *errmsg = NULL;
	int size = 0;
	MYSQL mysql;
	int res, i, len, Ram_id;
	int res1 = 1;
	char isBreak = 0;
	int64_t key, key2;
	int64_t keyfirst = 0;
	static int64_t key1 = 0;
	uint8_t bms_num = 0;
	static char flagread = 0;
	static unsigned int waittime = 0;
	sysPara *sys_cfg = SysConf_GetInfo();
	const int intime = 1000 * sys_cfg->dbSaveTime;
	if (mysql_init(&mysql) == NULL) // 初始化句柄mysql
	{
		printf("mysql_init failure!\n");
		return 1;
	}
	printf("mysql_init!\n");
	if (mysql_library_init(0, NULL, NULL) != 0) // 初始化mysql数据库
	{
		printf("mysql_library_init failure!\n");
		return 1;
	}
	else
	{
		printf("mysql_library_init!\n");
	}

	if (NULL == mysql_real_connect(&mysql,
								   "127.0.0.1",
								   "root",
								   "qwer1234",
								   NULL,
								   3306,
								   NULL,
								   0)) // 与mysql服务器建立连接
	{
		printf("mysql_real_connect failure!\n");
		mysql_library_end();
		return 1;
	}
	Creat_Database(&mysql);
	mysql_select_db(&mysql, "log_db");
	printf("mysql_real_connect!\n");
	printf("connect success!\n");
	if (mysql_set_character_set(&mysql, "utf8") != 0) // 设置中文字符集
	{
		printf("mysql_set_character_set failure!\n");
		mysql_close(&mysql);
		mysql_library_end();
		return 1;
	}
	printf("mysql_set_character_set!\n");
	while (1)
	{
		key = GetMSecsSinceEpoch();
		if (keyfirst == 0)
		{
			keyfirst = key;
		}
		else
		{
			keyfirst += intime;
			if (keyfirst < key)
			{
				//超过设定时间
				flagread = 0;
			}
			else
			{
				flagread = 1;
			}
		}

		tm_m.tm_year = ttvalue[0];
		tm_m.tm_mon = ttvalue[1];
		tm_m.tm_mday = ttvalue[2];
		tm_m.tm_hour = ttvalue[3];
		tm_m.tm_min = ttvalue[4];
		tm_m.tm_sec = ttvalue[5];
		isBreak = 1;
		//////////////////////数据库读写///////////////////////////
		res1 = 1;
		bzero_all(sqlstr);
		strcat(sqlstr, "START TRANSACTION;\0");
		if (mysql_query(&mysql, sqlstr))
		{
			printf("START TRANSACTION failed!\n");
		}
		if (0 == Insert_system_Table(&mysql))
		{
			res1 = 0;
		}
		if (0 == Insert_pcsModel_Table(&mysql))
		{
			res1 = 0;
		}
		// if (0 == Insert_pcsGroup_Table(&mysql))
		// {
		// 	res1 = 0;
		// }
		if (0 == Insert_meter_Table(&mysql))
		{
			res1 = 0;
		}
		// if (0 == Insert_sydy_Table(&mysql))
		// {
		// 	res1 = 0;
		// }
		if (0 == Insert_mv_Table(&mysql))
		{
			res1 = 0;
		}
		if (0 == Insert_fault_Table(&mysql))
		{
			res1 = 0;
		}
		if (0 == Insert_bms_Table(&mysql))
		{
			res1 = 0;
		}
		bzero_all(sqlstr);
		sprintf(sqlstr, "COMMIT;");
		if (mysql_query(&mysql, sqlstr)) {
			printf("COMMIT failed!\n");
		}
		if (0 == Insert_rack_Table(&mysql))
		{
			res1 = 0;
		}
		// if (0 == Insert_cell_temp_Table(&mysql))
		// {
		// 	res1 = 0;
		// }
		// if (0 == Insert_cell_vol_Table(&mysql))
		// {
		// 	res1 = 0;
		// }
		// if (0 == Insert_cell_pole_Table(&mysql))
		// {
		// 	res1 = 0;
		// }

		Del_Expire_Table(&mysql);
		if (res1 == 1)
		{
			isBreak = 1;
			break;
		}
		else
		{
			isBreak = 0;
		}
		usleep(10 * 1000);
		waittime = 0;
		while (++waittime < (50 * sys_cfg->dbSaveTime))
		{
			usleep(20 * 1000);
			int64_t key2 = GetMSecsSinceEpoch() - key;
			int intimetmp = (flagread == 0 ? (intime - 1) : intime);
			if (key2 >= intimetmp)
			{
				break;
			}
		}
	}
	mysql_close(&mysql);
	mysql_library_end();
	printf("mysql_library_end()!\n");
	return 1;
}
#endif

/**
 * @brief 数据库操作任务任务
 * @param[in] void *arg
 * @return 返回结果 无
 */
void *db_task(void *arg)
{

	while (1)
	{
		// 延时等堆簇数据更新
		// sleep(30);
		sleep(1);
#ifdef USE_DB
		Deal_database();
#endif
	}
}
