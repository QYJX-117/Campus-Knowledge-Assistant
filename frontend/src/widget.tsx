import React from "react";
import { createRoot, type Root } from "react-dom/client";
import Widget from "./widget/Widget";
import css from "./widget/widget.css?inline";

export interface HHUChatOptions {
  apiBaseUrl?: string;
  primaryColor?: string;
  title?: string;
  quickQuestions?: string[];
  loginUrl?: string;
  showSources?: boolean;
  draggable?: boolean;
  accessToken?: string;
}

interface HHUChatController {
  element: HTMLElement;
  open: () => void;
  close: () => void;
  destroy: () => void;
}

const TAG = "hhu-chat-widget";

class HHUChatElement extends HTMLElement {
  private root: Root | null = null;
  private mount: HTMLDivElement | null = null;

  connectedCallback() {
    if (this.root) return;
    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = css;
    shadow.appendChild(style);
    this.mount = document.createElement("div");
    shadow.appendChild(this.mount);
    this.root = createRoot(this.mount);
    this.renderWidget();
  }

  disconnectedCallback() {
    // React 18 warns when a custom element is removed while its parent tree
    // is still committing.  Defer cleanup one microtask and cancel it when
    // the element is reconnected during the same React commit.
    queueMicrotask(() => {
      if (this.isConnected) return;
      this.root?.unmount();
      this.root = null;
      this.mount = null;
    });
  }

  private renderWidget() {
    if (!this.root) return;
    let quickQuestions: string[] | undefined;
    try {
      const value = this.getAttribute("quick-questions");
      quickQuestions = value ? JSON.parse(value) : undefined;
    } catch {
      quickQuestions = undefined;
    }
    this.root.render(
      <React.StrictMode>
        <Widget
          title={this.getAttribute("title") || undefined}
          guestApiBase={this.getAttribute("api-base") || ""}
          accessToken={this.getAttribute("access-token") || ""}
          quickQuestions={quickQuestions}
          loginUrl={this.getAttribute("login-url") || ""}
          showSources={false}
          draggable={this.getAttribute("movable") === "true"}
        />
      </React.StrictMode>,
    );
  }
}

if (!customElements.get(TAG)) customElements.define(TAG, HHUChatElement);

function init(options: HHUChatOptions = {}): HHUChatController {
  const element = document.createElement(TAG) as HHUChatElement;
  if (options.apiBaseUrl) element.setAttribute("api-base", options.apiBaseUrl.replace(/\/$/, ""));
  if (options.primaryColor) element.style.setProperty("--river", options.primaryColor);
  if (options.title) element.setAttribute("title", options.title);
  if (options.loginUrl) element.setAttribute("login-url", options.loginUrl);
  if (options.quickQuestions) element.setAttribute("quick-questions", JSON.stringify(options.quickQuestions));
  if (options.showSources === false) element.setAttribute("show-sources", "false");
  if (options.draggable) element.setAttribute("movable", "true");
  if (options.accessToken) element.setAttribute("access-token", options.accessToken);
  document.body.appendChild(element);

  return {
    element,
    open: () => element.shadowRoot?.querySelector<HTMLElement>(".wg-bubble")?.click(),
    close: () => element.shadowRoot?.querySelector<HTMLButtonElement>(".wg-header__btn")?.click(),
    destroy: () => element.remove(),
  };
}

declare global {
  interface Window {
    HHUChat: { init: (options?: HHUChatOptions) => HHUChatController };
  }
}

window.HHUChat = { init };

export { init };
export default HHUChatElement;
