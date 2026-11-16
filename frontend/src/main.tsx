import ReactDOM from "react-dom/client";
import { useEffect } from "react";
import { BrowserRouter } from "react-router-dom";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { buildAntdTheme } from "./styles/antd-theme";
import { useThemeStore } from "./store/themeStore";
import "./styles/index.css";

function ThemeShell() {
  const theme = useThemeStore((s) => s.theme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }, [theme]);
  return (
    <ConfigProvider theme={buildAntdTheme(theme)} locale={zhCN}>
      <AntdApp>
        <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          <App />
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeShell />
);
