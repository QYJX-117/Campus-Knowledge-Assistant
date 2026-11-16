/** Custom Element: <campus-qa-widget> — auto-initializing Shadow DOM chat widget */
import React from "react";
import { createRoot, Root } from "react-dom/client";
import Widget from "./Widget";
import css from "./widget.css?inline";

const TAG = "campus-qa-widget";

class CampusQAWidget extends HTMLElement {
  private _root: Root | null = null;
  private _observer: MutationObserver | null = null;

  static get observedAttributes() {
    return ["title", "api-base", "access-token", "quick-questions", "login-url", "show-sources", "movable"];
  }

  connectedCallback() {
    if (this._root) return;

    const shadow = this.attachShadow({ mode: "open" });

    // Inject styles
    const style = document.createElement("style");
    style.textContent = css;
    shadow.appendChild(style);

    // Mount React root
    const mount = document.createElement("div");
    shadow.appendChild(mount);
    this._root = createRoot(mount);
    this._render();

    // Observe attribute changes from outside
    this._observer = new MutationObserver(() => this._render());
    this._observer.observe(this, { attributes: true, attributeFilter: CampusQAWidget.observedAttributes });
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    queueMicrotask(() => {
      if (this.isConnected) return;
      this._root?.unmount();
      this._root = null;
    });
  }

  attributeChangedCallback() {
    this._render();
  }

  private _render() {
    if (!this._root) return;
    const title = this.getAttribute("title") || undefined;
    const apiBase = this.getAttribute("api-base") || "";
    const loginUrl = this.getAttribute("login-url") || "";
    let quickQuestions: string[] | undefined;
    try {
      const raw = this.getAttribute("quick-questions");
      if (raw) quickQuestions = JSON.parse(raw);
    } catch {}

    this._root.render(
      <React.StrictMode>
        <Widget
          title={title}
          guestApiBase={apiBase}
          accessToken={this.getAttribute("access-token") || ""}
          quickQuestions={quickQuestions}
          loginUrl={loginUrl}
          showSources={false}
          draggable={this.getAttribute("movable") === "true"}
        />
      </React.StrictMode>,
    );
  }
}

// Register only once
if (!customElements.get(TAG)) {
  customElements.define(TAG, CampusQAWidget);
}

export default CampusQAWidget;
