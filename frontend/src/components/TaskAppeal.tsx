import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Field, Modal } from "./ui";

export function TaskAppealButton({
  sessionId,
  direction,
  grade,
  compact = false,
}: {
  sessionId?: string | null;
  direction?: string | null;
  grade?: string | null;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [taskNo, setTaskNo] = useState("1");
  const [reason, setReason] = useState<"ambiguity" | "rubric" | "defect" | "other">("ambiguity");
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const navigate = useNavigate();

  const REASON_TITLES: Record<string, string> = {
    ambiguity: "Неоднозначная формулировка условия",
    rubric: "Верное альтернативное решение не зачтено рубрикой",
    defect: "Техническая неточность в примере кода",
    other: "Другое замечание по заданию",
  };

  function submit() {
    setSubmitted(true);
  }

  function openTrioAppeal() {
    const body = `Апелляция по заданию №${taskNo} сессии ${sessionId ? sessionId.slice(0, 8) : "теста"} (${REASON_TITLES[reason]}): ${comment.trim() || "прошу проверить решение экспертом и представителем ФСП"}`;
    setOpen(false);
    navigate(`/candidate/trio?topic=appeal&body=${encodeURIComponent(body)}`);
  }

  return (
    <>
      <button
        type="button"
        className={compact ? "text-xs font-semibold text-brand-plum hover:underline" : "btn-ghost"}
        onClick={() => {
          setSubmitted(false);
          setOpen(true);
        }}
        data-testid="appeal-task-btn"
      >
        Оспорить задание
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Оспорить задание теста (апелляция с разбором)">
        <div className="space-y-4 text-sm" data-testid="appeal-task-modal">
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="rounded-xl bg-[#ECEAF8] p-2.5 font-semibold text-brand-night">1. Заявка по заданию</div>
            <div className="rounded-xl bg-white p-2.5 font-semibold text-brand-ink ring-1 ring-brand-night/10">2. Разбор эксперта и ФСП</div>
            <div className="rounded-xl bg-emerald-50 p-2.5 font-semibold text-emerald-900">3. Пересчёт и решение</div>
          </div>
          {!submitted ? (
            <>
              <p className="text-brand-ink/75">
                Если вы считаете, что условие задания допускает двоякое толкование или ваше альтернативное решение корректно, подайте апелляцию. Ключи банка не раскрываются, но эксперт и представитель ФСП проверят ваш ответ по логу сессии.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Номер задания в попытке" htmlFor="appeal-task-no">
                  <input
                    id="appeal-task-no"
                    type="number"
                    min={1}
                    max={30}
                    className="input"
                    value={taskNo}
                    onChange={(e) => setTaskNo(e.target.value)}
                  />
                </Field>
                <Field label="Причина обращения" htmlFor="appeal-reason">
                  <select
                    id="appeal-reason"
                    className="input"
                    value={reason}
                    onChange={(e) => setReason(e.target.value as any)}
                  >
                    {Object.entries(REASON_TITLES).map(([k, t]) => (
                      <option key={k} value={k}>{t}</option>
                    ))}
                  </select>
                </Field>
              </div>
              <Field label="Обоснование вашего решения" htmlFor="appeal-comment">
                <textarea
                  id="appeal-comment"
                  className="input min-h-[90px]"
                  maxLength={1500}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Опишите ход вашего решения и почему вы считаете ответ верным"
                />
              </Field>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={comment.trim().length < 5}
                  onClick={submit}
                  data-testid="appeal-submit-btn"
                >
                  Зарегистрировать апелляцию
                </button>
                <button type="button" className="btn-ghost" onClick={openTrioAppeal}>
                  Передать в трёхстороннюю связь с ФСП →
                </button>
              </div>
            </>
          ) : (
            <div className="space-y-3">
              <Alert kind="ok">
                Заявка на апелляцию по заданию №{taskNo}{direction || grade ? ` (${[direction, grade].filter(Boolean).join(" · ")})` : ""} зарегистрирована и направлена на экспертный разбор. Если по итогам разбора балл изменится, паспорт грейда обновится автоматически.
              </Alert>
              <div className="flex flex-wrap gap-3">
                <button type="button" className="btn-primary" onClick={openTrioAppeal}>
                  Обсудить в трёхстороннем канале с ФСП →
                </button>
                <Link to="/candidate/trio?topic=appeal" className="btn-ghost" onClick={() => setOpen(false)}>
                  Открыть каналы ФСП
                </Link>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
