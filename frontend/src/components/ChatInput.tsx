import { useState } from "react";
import { Icon } from "./Icon";

export function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (q: string) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState("");

  const send = () => {
    const q = text.trim();
    if (!q || disabled) return;

    onSend(q);
    setText("");
  };

  return (
    <div className="bg-transparent">
      <div className="relative flex items-center rounded-xl border border-border bg-transparent p-2 shadow-lg transition-all duration-200 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/30">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={1}
          placeholder="Hỏi AI Data Agent về dữ liệu Feature Store..."
          style={{ minHeight: "48px" }}
          className="max-h-[120px] w-full resize-none border-none bg-transparent px-4 py-3 text-base leading-6 text-on-surface outline-none"
        />

        <div className="flex flex-shrink-0 items-center p-2">
          <button
            type="button"
            onClick={send}
            disabled={disabled || !text.trim()}
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-container text-white shadow-sm transition-colors hover:bg-primary-hover disabled:opacity-40"
            aria-label="Gửi câu hỏi"
          >
            <Icon name="send" />
          </button>
        </div>
      </div>

      <div className="mt-2 bg-transparent text-center text-[11px] text-text-secondary">
        AI Data Agent có thể mắc lỗi. Vui lòng kiểm tra lại SQL được tạo.
      </div>
    </div>
  );
}