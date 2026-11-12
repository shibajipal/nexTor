"""
nexTor TUI — Theme constants & ASCII art.
Font: JetBrainsMono Nerd Font
Palette: dark olive green background (#2E3A1F), white text (#FFFFFF), sage border (#C8D6A0)
"""

#Unified Dark Olive Palette 
BG_DARK_OLIVE = "#2E3A1F"   # Uniform dark olive green for entire screen & panels
FG_PRIMARY    = "#FFFFFF"   # White text – clean, normal weight (no bold)
FG_MUTED      = "#A0A880"   # Muted sage for secondary placeholders / hints
BORDER        = "#C8D6A0"   # Light olive / sage rounded border lines

# ASCII Art Logo 
# ANSI Shadow "NEXTOR" – 52 chars wide, 6 lines high
# Rendered in raw text with no_wrap to prevent terminal jank
NEXTOR_ASCII = r"""
███╗   ██╗███████╗██╗  ██╗████████╗ ██████╗ ██████╗ 
████╗  ██║██╔════╝╚██╗██╔╝╚══██╔══╝██╔═══██╗██╔══██╗
██╔██╗ ██║█████╗   ╚███╔╝    ██║   ██║   ██║██████╔╝
██║╚██╗██║██╔══╝   ██╔██╗    ██║   ██║   ██║██╔══██╗
██║ ╚████║███████╗██╔╝ ██╗   ██║   ╚██████╔╝██║  ██║
╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
""".strip("\n")

# Compact fallback for narrow terminals (< 56 cols)
NEXTOR_ASCII_COMPACT = r"""
 _  _ ____ _  _ ___ ____ ____
 |\ | |___  \/   |  |  | |--/
 | \| |___ _/\_  |  |__| |  \
""".strip("\n")
