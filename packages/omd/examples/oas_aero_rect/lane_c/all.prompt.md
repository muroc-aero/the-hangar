# Task: Rectangular Wing Aero Study

Run an aero analysis and twist optimization of a rectangular wing,
then compare the results.

## Part 1: Baseline Analysis

Analyze a rectangular wing (10 m span, 1 m chord) at Mach=0.84,
alpha=5 deg using VLM with viscous drag. Report CL, CD, and L/D.

## Part 2: Twist Optimization

Optimize the twist distribution to minimize CD while holding CL = 0.5.
Use twist_cp bounds of [-10, 15] deg and SLSQP optimizer.

## Part 3: Comparison

Compare baseline and optimized CD. Report the drag reduction in percent.
Generate planform and lift distribution plots for both cases.

Use `/omd-cli-guide` to learn the plan YAML structure.
