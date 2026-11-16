import { Component, ReactNode } from "react";
import { Result, Button } from "antd";

interface Props { children: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };
  static getDerivedStateFromError(e: Error) { return { hasError: true, error: e }; }
  render() {
    if (this.state.hasError) return (
      <Result status="error" title="页面出错了" subTitle={this.state.error?.message}
        extra={<Button type="primary" onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}>刷新页面</Button>} />
    );
    return this.props.children;
  }
}
