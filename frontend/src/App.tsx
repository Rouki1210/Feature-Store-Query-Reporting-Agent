import { useEffect, useRef, useState } from "react";
import { ask } from "./api";
import type { AskResponse } from "./types";
import { Sidebar } from "./components/Sidebar";
import { ChatInput } from "./components/ChatInput";
import { Message } from "./components/Message";
import { Icon } from "./components/Icon";

interface Turn {
  question: string;
  response?: AskResponse;
  failed?: string;
}

const EXAMPLES = [
  "Tổng chi tiêu GSM 3 tháng gần nhất",
  "Số đơn VinFast hoàn thành trong 12 tháng gần nhất",
  "Khách hàng thế nào", // mơ hồ → clarify
];

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const lastTurnRef = useRef<HTMLDivElement>(null);
  const prevLen = useRef(0);

  useEffect(() => {
    // Chỉ khi GỬI câu mới (turns tăng) → nhảy tới câu vừa gửi. Response về (cùng
    // độ dài) KHÔNG cuộn, để đọc thoải mái và tự cuộn xem hết câu trả lời.
    if (turns.length > prevLen.current) {
      lastTurnRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    prevLen.current = turns.length;
  }, [turns.length]);

  const send = async (q: string) => {
    if (pending) return;
    setTurns((t) => [...t, { question: q }]);
    setPending(true);
    try {
      const resp = await ask(q, sessionId);
      setSessionId(resp.session_id ?? sessionId);
      setTurns((t) => {
        const c = [...t];
        c[c.length - 1] = { ...c[c.length - 1], response: resp };
        return c;
      });
    } catch (e) {
      setTurns((t) => {
        const c = [...t];
        c[c.length - 1] = { ...c[c.length - 1], failed: String(e) };
        return c;
      });
    } finally {
      setPending(false);
    }
  };

  const newQuery = () => {
    setTurns([]);
    setSessionId(null);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background text-on-surface">
      <Sidebar onNewQuery={newQuery} />

      <div className="flex h-full w-full min-w-0 flex-1 flex-col">
        {/* Header */}
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-surface/80 px-8 backdrop-blur-md">
          <div className="text-[20px] font-extrabold text-primary">Feature Store Agent</div>
          <div className="flex items-center gap-2 text-text-secondary">
            <button className="rounded-full p-2 transition-colors hover:text-primary">
              <Icon name="notifications" />
            </button>
            <button className="rounded-full p-2 transition-colors hover:text-primary">
              <Icon name="help_outline" />
            </button>
            <div className="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Icon name="person" className="text-[18px]" />
            </div>
          </div>
        </header>

        {/* Chat canvas — cuộn trọn vẹn giữa header và thanh nhập */}
        <main className="flex flex-1 justify-center overflow-y-auto p-4 pb-6 md:p-8 md:pb-6">
          <div className="flex w-full max-w-[800px] flex-col gap-6">
            {turns.length === 0 && (
              <div className="mx-auto max-w-2xl pt-10 text-center">
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon name="hub" className="text-[26px]" fill />
                </div>
                <h2 className="text-lg font-semibold text-text-primary">
                  Hỏi về dữ liệu GSM &amp; VinFast bằng tiếng Việt
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  Agent chọn feature, sinh SQL (luôn hiển thị để kiểm chứng) và trả bảng/biểu đồ.
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((q) => (
                    <button
                      key={q}
                      onClick={() => send(q)}
                      className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-on-surface-variant transition-colors hover:border-primary hover:text-primary"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((turn, i) => (
              <div
                key={i}
                ref={i === turns.length - 1 ? lastTurnRef : undefined}
                className="flex scroll-mt-4 flex-col gap-4"
              >
                <div className="flex justify-end">
                  <div
                    className="max-w-[85%] bg-primary-container px-5 py-3.5 text-white shadow-sm"
                    style={{ borderRadius: "16px 16px 4px 16px" }}
                  >
                    {turn.question}
                  </div>
                </div>
                {turn.failed ? (
                  <div className="rounded-lg border border-error/40 bg-error/10 px-4 py-3 text-sm text-error">
                    ⚠ Không gọi được backend ({turn.failed}). Kiểm tra server đang chạy ở{" "}
                    <code>:8000</code>.
                  </div>
                ) : turn.response ? (
                  <Message response={turn.response} onQuickReply={send} />
                ) : (
                  <div className="flex items-center gap-2 text-sm text-text-secondary">
                    <Icon name="autorenew" className="animate-spin text-[18px]" />
                    Đang route → generate → validate → execute…
                  </div>
                )}
              </div>
            ))}
          </div>
        </main>

        {/* Thanh nhập — card nổi trên nền gradient (giống design), nhưng là flex
            child (không phủ nội dung → vẫn cuộn xem hết câu trả lời) */}
        <div className="shrink-0 bg-transparent px-4 pb-4 pt-6 md:px-8 md:pb-6">
          <div className="mx-auto w-full max-w-[800px]">
            <ChatInput onSend={send} disabled={pending} />
          </div>
        </div>
      </div>
    </div>
  );
}
