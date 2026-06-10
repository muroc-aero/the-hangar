"""MCP tool implementations for the omd server.

Each module groups tools by workflow stage; ``hangar.omd.server`` registers
them. Tool functions call the same implementation functions as ``omd-cli``,
so the two front ends never drift.
"""
