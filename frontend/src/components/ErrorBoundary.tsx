import { Component, type ErrorInfo, type ReactNode } from "react";

/** Ошибка отрисовки страницы → понятный экран с «Обновить» вместо пустой страницы.
 *  10.10 под нагрузкой (docs/LOAD.md, раздел 6) часть запросов падала 500, и у двух человек на проверке был
 *  белый экран: исключение при отрисовке снимает всё дерево React. resetKey — адрес страницы: переход по меню
 *  снимает ошибку без перезагрузки. */
export class ErrorBoundary extends Component<{ resetKey?: string; children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Ошибка отрисовки страницы", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="mx-auto flex min-h-[60vh] max-w-xl items-center px-4 py-10" role="alert">
        <div className="card w-full">
          <h1 className="text-xl font-bold text-brand-night">Не удалось показать страницу</h1>
          <p className="mt-2 text-brand-ink/65">
            Сервер мог ответить с задержкой или ошибкой. Данные не потеряны — обновите страницу через несколько секунд.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={() => location.reload()}>Обновить</button>
            <a className="btn-ghost" href="/">На главную</a>
          </div>
        </div>
      </main>
    );
  }
}
