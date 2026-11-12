package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

var (
	background = lipgloss.Color("#282a36")
	foreground = lipgloss.Color("#f8f8f2")
	gray       = lipgloss.Color("#9699a8")
	border     = lipgloss.Color("#858795")
	pink       = lipgloss.Color("#ff79c6")
	magenta    = lipgloss.Color("#bd93f9")
	cyan       = lipgloss.Color("#8be9fd")
	green      = lipgloss.Color("#50fa7b")
	yellow     = lipgloss.Color("#ffb86c")
	red        = lipgloss.Color("#ff5555")
	blue       = lipgloss.Color("#58a6ff")
	graphDark  = lipgloss.Color("#252837")
)

type model struct {
	width  int
	height int
}

func (m model) Init() tea.Cmd { return nil }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
	case tea.KeyMsg:
		if msg.String() == "q" || msg.String() == "ctrl+c" {
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m model) View() string {
	width := m.width
	if width < 110 {
		width = 110
	}
	height := m.height
	if height < 34 {
		height = 34
	}

	availableWidth := width - 2
	availableHeight := height - 1
	leftWidth := int(float64(availableWidth) * 0.60)
	rightWidth := availableWidth - leftWidth

	headerHeight := 9
	listHeight := availableHeight - headerHeight
	if listHeight < 6 {
		listHeight = 6
	}

	graphHeight := 18
	chunkHeight := 6
	detailHeight := availableHeight - graphHeight - chunkHeight
	if detailHeight < 10 {
		graphHeight = 14
		detailHeight = availableHeight - graphHeight - chunkHeight
	}

	left := lipgloss.JoinVertical(
		lipgloss.Left,
		lipgloss.JoinHorizontal(lipgloss.Top, renderServer(leftWidth/3, headerHeight), renderActivityLog(leftWidth-leftWidth/3, headerHeight)),
		renderDownloads(leftWidth, listHeight),
	)
	right := lipgloss.JoinVertical(
		lipgloss.Left,
		renderNetworkActivity(rightWidth, graphHeight),
		renderFileDetails(rightWidth, detailHeight),
		renderChunkMap(rightWidth, chunkHeight),
	)

	body := lipgloss.JoinHorizontal(lipgloss.Top, left, right)
	footer := renderFooter(availableWidth)
	return lipgloss.NewStyle().Background(background).Foreground(foreground).Render(
		lipgloss.JoinVertical(lipgloss.Left, body, footer),
	)
}

func renderServer(width, height int) string {
	logo := "   _______\n  / ___/ / / / ___/ __ '/ _ \\\n (__  ) /_/ / /  / /_/ /  __/\n/____/\\__,_/_/   \\__, /\\___/\n                /____/"
	logo = lipgloss.NewStyle().Foreground(magenta).Bold(true).Render(logo)
	content := lipgloss.Place(width-2, height-2, lipgloss.Center, lipgloss.Center,
		lipgloss.JoinVertical(lipgloss.Center, logo, "", lipgloss.NewStyle().Foreground(gray).Render("Local mode")),
	)
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" Server "), content, width, height, border)
}

func renderActivityLog(width, height int) string {
	lines := []string{
		logLine("[12:34:03]", "▮ Paused: ", "conference-recording.mp4", yellow),
		logLine("[12:34:04]", "▾ Started: ", "project-backup.tar.zst", green),
		logLine("[12:34:05]", "▸ Started: ", "game-update.bin", green),
		logLine("[12:34:06]", "▾ Resumed: ", "game-update.bin", green),
		logLine("[12:34:07]", "▸ Started: ", "game-update.bin", green),
		logLine("[12:34:08]", "▾ Started: ", "holiday-photos.zip", green),
		logLine("[12:34:09]", "✓ Done: ", "holiday-photos.zip (13.36 MiB/s)", magenta),
		logLine("[12:34:10]", "▾ Started: ", "dataset.csv", green),
		logLine("[12:34:11]", "✖ Error: ", "dataset.csv", red),
	}
	content := strings.Join(lines, "\n")
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" Activity Log [l] "), content, width, height, border)
}

func renderDownloads(width, height int) string {
	tabs := strings.Join([]string{
		lipgloss.NewStyle().Foreground(pink).Bold(true).Border(lipgloss.RoundedBorder()).BorderForeground(pink).Padding(0, 1).Render("All (7)"),
		lipgloss.NewStyle().Foreground(gray).Border(lipgloss.RoundedBorder()).BorderForeground(border).Padding(0, 1).Render("Queued (3)"),
		lipgloss.NewStyle().Foreground(gray).Border(lipgloss.RoundedBorder()).BorderForeground(border).Padding(0, 1).Render("Active (2)"),
		lipgloss.NewStyle().Foreground(gray).Border(lipgloss.RoundedBorder()).BorderForeground(border).Padding(0, 1).Render("Done (2)"),
	}, " ")

	rows := []string{
		"",
		downloadRow("fedora-workstation.iso", "↓ Downloading", "50%", "18 MiB/s (Limit: 24 MiB/s)", "128 MiB / 256 MiB", green),
		"",
		downloadRow("design-assets.zip", "∙ Queued", "0%", "0 B/s", "0 B / 512 MiB", yellow),
		"",
		selectedDownloadRow("conference-recording.mp4", "Ⅱ Paused", "50%", "384 MiB / 768 MiB", yellow, width-6),
		"",
		downloadRow("project-backup.tar.zst", "⋮ Pausing...", "50%", "512 MiB / 1.0 GiB", "", yellow),
		"",
		downloadRow("game-update.bin", "⋮ Resuming...", "50%", "640 MiB / 1.3 GiB", "", green),
		"",
		downloadRow("holiday-photos.zip", "✓ Completed", "", "21 MiB/s", "1.5 GiB", magenta),
		"",
		downloadRow("dataset.csv", "✖ Error", "50%", "", "896 MiB / 1.8 GiB", red),
	}
	content := lipgloss.JoinVertical(lipgloss.Left, tabs, strings.Join(rows, "\n"))
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" Downloads "), content, width, height, pink)
}

func renderNetworkActivity(width, height int) string {
	innerWidth := width - 4
	graphWidth := innerWidth - 13
	if graphWidth < 20 {
		graphWidth = 20
	}
	chart := graphChart(graphWidth, height-5)
	axis := []string{"29 MiB/s", "23 MiB/s", "17 MiB/s", "11 MiB/s", "5.7 MiB/s", "0 MiB/s"}
	var chartLines []string
	chartRows := strings.Split(chart, "\n")
	for i, line := range chartRows {
		label := ""
		if i < len(axis) {
			label = lipgloss.NewStyle().Foreground(cyan).Render(axis[i])
		}
		chartLines = append(chartLines, line+"  "+label)
	}
	stats := lipgloss.JoinVertical(lipgloss.Left,
		lipgloss.NewStyle().Foreground(cyan).Bold(true).Render("▼ 18 MiB/s"),
		lipgloss.NewStyle().Foreground(gray).Render("  (151 Mbps)"),
		"",
		lipgloss.NewStyle().Foreground(gray).Render("Top: ")+lipgloss.NewStyle().Foreground(cyan).Bold(true).Render("25 MiB/s"),
		lipgloss.NewStyle().Foreground(gray).Render("  (209 Mbps)"),
		"",
		lipgloss.NewStyle().Foreground(gray).Render("Total: ")+lipgloss.NewStyle().Foreground(cyan).Bold(true).Render("4.0 GiB"),
	)
	content := lipgloss.JoinHorizontal(lipgloss.Top, stats, lipgloss.NewStyle().Foreground(gray).Render("│"), strings.Join(chartLines, "\n"))
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" Network Activity "), content, width, height, cyan)
}

func renderFileDetails(width, height int) string {
	divider := lipgloss.NewStyle().Foreground(border).Render(strings.Repeat("─", width-4))
	content := strings.Join([]string{
		lipgloss.NewStyle().Foreground(yellow).Render("Ⅱ Paused"),
		"",
		labelValue("File:", "conference-recording.mp4"),
		"",
		labelValue("Path:", "/Downloads"),
		"",
		labelValue("ID:", "00000000-0000-4000-8000-000000000003"),
		"",
		labelValue("URL:", "https://example.com/conference-recording.mp4"),
		"",
		divider,
		"",
		progressLine(width - 6),
		"",
		divider,
		"",
		labelValue("Size:", "384 MiB / 768 MiB") + "        " + labelValue("Time:", "1:04"),
		labelValue("Speed:", "Paused") + "                 " + labelValue("ETC:", "∞"),
	}, "\n")
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" File Details "), content, width, height, border)
}

func renderChunkMap(width, height int) string {
	cells := make([]string, 0, 120)
	for i := 0; i < 80; i++ {
		color := green
		if i > 58 {
			color = yellow
		}
		cells = append(cells, lipgloss.NewStyle().Foreground(color).Render("▪"))
	}
	for i := 0; i < 40; i++ {
		cells = append(cells, lipgloss.NewStyle().Foreground(graphDark).Render("▪"))
	}
	columns := width / 2
	if columns < 10 {
		columns = 10
	}
	var rows []string
	for start := 0; start < len(cells); start += columns {
		end := start + columns
		if end > len(cells) {
			end = len(cells)
		}
		rows = append(rows, "  "+strings.Join(cells[start:end], " "))
	}
	return btopBox("", lipgloss.NewStyle().Foreground(gray).Bold(true).Render(" Chunk Map "), strings.Join(rows, "\n"), width, height, border)
}

func renderFooter(width int) string {
	left := lipgloss.NewStyle().Foreground(gray).Render("h toggle help  ·  ? bug report")
	right := lipgloss.JoinHorizontal(lipgloss.Center,
		lipgloss.NewStyle().Foreground(cyan).Render("↓ 18 MiB/s"),
		lipgloss.NewStyle().Foreground(gray).Render("  │  "),
		lipgloss.NewStyle().Foreground(yellow).Render("⚡ ∞"),
		lipgloss.NewStyle().Foreground(gray).Render("  │  "),
		lipgloss.NewStyle().Foreground(gray).Render("⏻"),
		lipgloss.NewStyle().Foreground(gray).Render("  │  "),
		lipgloss.NewStyle().Foreground(blue).Render("vvisual-test"),
	)
	gap := width - lipgloss.Width(left) - lipgloss.Width(right)
	if gap < 1 {
		gap = 1
	}
	return lipgloss.JoinHorizontal(lipgloss.Top, "  "+left, strings.Repeat(" ", gap), right, "  ")
}

func btopBox(leftTitle, rightTitle, content string, width, height int, color lipgloss.Color) string {
	if width < 4 {
		width = 4
	}
	if height < 3 {
		height = 3
	}
	innerWidth := width - 2
	borderStyle := lipgloss.NewStyle().Foreground(color)
	leftWidth := lipgloss.Width(leftTitle)
	rightWidth := lipgloss.Width(rightTitle)
	remaining := innerWidth - leftWidth - rightWidth - 2
	if remaining < 0 {
		remaining = 0
	}
	top := borderStyle.Render("╭─") + leftTitle + borderStyle.Render(strings.Repeat("─", remaining)) + rightTitle + borderStyle.Render("─╮")
	bottom := borderStyle.Render("╰" + strings.Repeat("─", innerWidth) + "╯")

	lines := strings.Split(content, "\n")
	bodyHeight := height - 2
	wrapped := make([]string, bodyHeight)
	for i := 0; i < bodyHeight; i++ {
		line := ""
		if i < len(lines) {
			line = lines[i]
		}
		line = lipgloss.NewStyle().Width(innerWidth).MaxWidth(innerWidth).Render(line)
		wrapped[i] = borderStyle.Render("│") + line + borderStyle.Render("│")
	}
	return lipgloss.JoinVertical(lipgloss.Left, top, strings.Join(wrapped, "\n"), bottom)
}

func logLine(time, action, file string, color lipgloss.Color) string {
	return lipgloss.NewStyle().Foreground(green).Render(time) + " " + lipgloss.NewStyle().Foreground(color).Render(action+file)
}

func downloadRow(name, status, percent, details, total string, color lipgloss.Color) string {
	meta := []string{status}
	if percent != "" {
		meta = append(meta, percent)
	}
	if details != "" {
		meta = append(meta, details)
	}
	if total != "" {
		meta = append(meta, total)
	}
	return "  " + lipgloss.NewStyle().Foreground(foreground).Render(name) + "\n  " + lipgloss.NewStyle().Foreground(color).Render(strings.Join(meta, "  •  "))
}

func selectedDownloadRow(name, status, percent, total string, color lipgloss.Color, width int) string {
	line := downloadRow(name, status, percent, total, "", color)
	return lipgloss.NewStyle().Background(lipgloss.Color("#513d54")).Width(width).Render(line)
}

func labelValue(label, value string) string {
	return lipgloss.NewStyle().Foreground(cyan).Render(fmt.Sprintf("%-7s", label)) + lipgloss.NewStyle().Foreground(foreground).Bold(label == "File:").Render(value)
}

func progressLine(width int) string {
	filled := int(float64(width-10) * 0.50)
	if filled < 1 {
		filled = 1
	}
	bar := lipgloss.NewStyle().Foreground(pink).Render(strings.Repeat("█", filled)) + lipgloss.NewStyle().Foreground(graphDark).Render(strings.Repeat("░", width-10-filled))
	return lipgloss.NewStyle().Foreground(cyan).Render("Progress:") + " " + bar + "  " + lipgloss.NewStyle().Foreground(foreground).Render("50%")
}

func graphChart(width, height int) string {
	if height < 6 {
		height = 6
	}
	levels := []int{1, 2, 4, 3, 5, 6, 3, 2, 4, 7, 5, 8, 6, 2, 3, 5, 4, 7, 3, 6, 8, 5, 4, 2, 3, 6, 5, 7, 4, 6, 8, 5}
	var rows []string
	for row := height - 1; row >= 0; row-- {
		var line strings.Builder
		for x := 0; x < width; x++ {
			level := levels[(x*len(levels))/width]
			if level >= row+1 {
				shade := magenta
				if row > height/2 {
					shade = lipgloss.Color("#ab47bc")
				} else if row > height/3 {
					shade = lipgloss.Color("#ce93d8")
				} else {
					shade = lipgloss.Color("#e1bee7")
				}
				line.WriteString(lipgloss.NewStyle().Foreground(shade).Render("█"))
			} else if row%2 == 0 {
				line.WriteString(lipgloss.NewStyle().Foreground(border).Render("·"))
			} else {
				line.WriteString(" ")
			}
		}
		rows = append(rows, line.String())
	}
	return strings.Join(rows, "\n")
}

func main() {
	program := tea.NewProgram(model{}, tea.WithAltScreen())
	if _, err := program.Run(); err != nil {
		panic(err)
	}
}
