# Task: Size an Archer Midnight eVTOL

You are sizing an Archer Midnight-class lift+cruise eVTOL: a roughly two-tonne
vectored-thrust urban-air-mobility aircraft on a short hop (about 30 mi at a
1500 ft cruise). Find its **sized** maximum takeoff mass -- the mass it settles
at once battery and structure masses close against the mission energy -- and
report the mission energy and peak electric power at that sized point.

## What matters

- Size the vehicle with the gradient-capable native eVTOL formulation, not the
  finite-difference black-box fallback.
- Use the Archer Midnight baseline that ships with the tooling. You do not have
  a config file to load, so reach for the built-in vehicle rather than a path
  on disk, and customise from there only if you need to.
- Confirm the sizing loop actually converged before you trust the numbers.

## Report

The sized takeoff mass, the total mission energy, and the peak electric power.
Judge whether the sized mass is plausible for a two-tonne-class eVTOL on this
mission and record that interpretation.

This task deliberately does not name the factory, vehicle template, solver, or
parameter keys. Consult the server's own reference material to choose them.
