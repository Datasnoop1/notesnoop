/** Brand colors and shared styling for Excel and PDF exports. */

export const BRAND = {
  headerBg: "1E293B",      // slate-800
  headerFont: "FFFFFF",
  sectionBg: "F1F5F9",     // slate-100
  accentBorder: "0D7377",   // brand teal
  greenFill: "ECFDF5",
  greenFont: "059669",
  redFill: "FFF1F2",
  redFont: "E11D48",
  amberFill: "FFFBEB",
  amberFont: "D97706",
  lightBorder: "E2E8F0",    // slate-200
};

// PDF colors (RGB arrays)
export const PDF = {
  headerBg: [30, 41, 59] as [number, number, number],
  headerFont: [255, 255, 255] as [number, number, number],
  accentLine: [13, 115, 119] as [number, number, number],
  textDark: [30, 41, 59] as [number, number, number],
  textMuted: [100, 116, 139] as [number, number, number],
  sectionBg: [241, 245, 249] as [number, number, number],
};
