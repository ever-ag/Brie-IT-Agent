#!/usr/bin/env python3
"""
Quick fix for DL detection pattern in action processor
"""

# The issue is in the group_patterns around line 1682
# Current pattern: r'add me to (?:the )?([A-Za-z0-9\s_-]+?)\s+dl\b'
# Fixed pattern should be: r'add (?:[A-Za-z\s]+\s+)?to (?:the )?([A-Za-z0-9\s_-]+?)\s+dl\b'

# This will match:
# - "add me to the localemployees dl"
# - "add Alex Goin to the localemployees dl" 
# - "add to the localemployees dl"

print("Fixed pattern: r'add (?:[A-Za-z\\s]+\\s+)?to (?:the )?([A-Za-z0-9\\s_-]+?)\\s+dl\\b'")
