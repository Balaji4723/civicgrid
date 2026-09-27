import type { Config } from "tailwindcss";

/* Palette from the brief, named by what each colour MEANS so it stays consistent across portals:
   ok = green (segregated / success)   track = blue (worker / tracking)   auth = purple (authority / facility)
   proc = orange (process / risk)      flag = red (discrepancy / flagged)                                   */
const scale = (b50: string, b100: string, b500: string, b600: string, b700: string) => ({
  50: b50, 100: b100, 500: b500, 600: b600, 700: b700,
});

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#17231C", soft: "#4A5A50", faint: "#7B8B80" },
        paper: "#F4F7F5",
        line: "#DCE4DE",
        ok: scale("#E8F5EC", "#CFEBD8", "#2A9D5C", "#1E8449", "#17683A"),
        track: scale("#E7F0FB", "#CFE0F6", "#3A78C9", "#2563B0", "#1C4E8C"),
        auth: scale("#F0EAFA", "#DFD2F3", "#8558C8", "#6D3FB2", "#55308D"),
        proc: scale("#FDF1E2", "#FADFBD", "#EA8A2B", "#D9700F", "#AD5808"),
        flag: scale("#FCE9EB", "#F7CDD2", "#D8505E", "#C93545", "#A12634"),
      },
      fontFamily: {
        sans: ['"Segoe UI"', "system-ui", "-apple-system", "Roboto", '"Helvetica Neue"', "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
