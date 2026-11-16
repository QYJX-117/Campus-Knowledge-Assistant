import { theme as antdThemeCore } from "antd";
import type { ThemeConfig } from "antd";
import type { Theme } from "../store/themeStore";

const { defaultAlgorithm, darkAlgorithm } = antdThemeCore;

const lightTokens = {
  colorPrimary: "#0B6FCC",
  colorSuccess: "#10B981",
  colorWarning: "#F59E0B",
  colorError: "#EF4444",
  colorInfo: "#0B6FCC",
  borderRadius: 10,
  colorBgContainer: "#FFFFFF",
  colorBgLayout: "#F3F8FC",
  fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif',
  fontSize: 15,
  colorText: "#1E293B",
  colorTextSecondary: "#64748B",
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
};

const darkTokens = {
  colorPrimary: "#59A8FF",
  colorSuccess: "#34D399",
  colorWarning: "#FBBF24",
  colorError: "#F87171",
  colorInfo: "#59A8FF",
  borderRadius: 10,
  colorBgContainer: "#121A24",
  colorBgLayout: "#081018",
  fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif',
  fontSize: 15,
  colorText: "#E5EEF8",
  colorTextSecondary: "#93A4B7",
  boxShadow: "0 12px 30px rgba(0,0,0,0.24)",
};

export function buildAntdTheme(mode: Theme): ThemeConfig {
  const dark = mode === "dark";
  return {
    algorithm: dark ? darkAlgorithm : defaultAlgorithm,
    token: dark ? darkTokens : lightTokens,
    components: {
      Layout: dark
        ? {
            siderBg: "#09121B",
            headerBg: "#0E1620",
            bodyBg: "#081018",
            triggerBg: "#0D1722",
          }
        : {
            siderBg: "#062D4F",
            headerBg: "#FFFFFF",
            bodyBg: "#F3F8FC",
            triggerBg: "#062D4F",
          },
      Menu: {
        darkItemBg: dark ? "#09121B" : "#062D4F",
        darkItemSelectedBg: dark ? "#173249" : "#0B6FCC",
        darkItemColor: dark ? "rgba(229,238,248,0.74)" : "rgba(255,255,255,0.72)",
        itemBorderRadius: 8,
        itemMarginInline: 8,
        fontSize: 15,
      },
      Card: { borderRadiusLG: 16, paddingLG: 24 },
      Button: { borderRadius: 8, controlHeight: 40, primaryShadow: "0 4px 14px rgba(11,111,204,0.28)" },
      Table: dark
        ? { borderRadius: 12, headerBg: "#101926", headerBorderRadius: 12 }
        : { borderRadius: 12, headerBg: "#F1F5F9", headerBorderRadius: 12 },
      Input: { borderRadius: 8, controlHeight: 40, activeShadow: "0 0 0 2px rgba(11,111,204,0.15)" },
      Select: { borderRadius: 8, controlHeight: 40 },
      Tag: { borderRadiusSM: 6 },
      Modal: { borderRadiusLG: 16 },
      Statistic: { contentFontSize: 28 },
    },
  };
}

export const antdTheme = buildAntdTheme("light");
