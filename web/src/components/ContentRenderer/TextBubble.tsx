interface Props {
  text: string;
}

export function TextBubble({ text }: Props) {
  return (
    <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {text}
    </div>
  );
}
