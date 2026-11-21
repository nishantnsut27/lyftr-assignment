import Markdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function MarkdownReply({ content }: { content: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) => {
        const safe = defaultUrlTransform(url);
        return /^(https?:|mailto:|\/|#)/i.test(safe) ? safe : '';
      }}
      components={{
        a: ({ href, children }) =>
          href ? (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          ),
        img: ({ alt }) => <span>{alt}</span>,
        pre: ({ children }) => (
          <pre tabIndex={0} aria-label="Code block">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Reply table"
          >
            <table>{children}</table>
          </div>
        ),
      }}
    >
      {content}
    </Markdown>
  );
}
