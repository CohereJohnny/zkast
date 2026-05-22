'use client';

import { type VariantProps, cva } from 'class-variance-authority';
import { createElement } from 'react';

import { cn } from '../lib/cn';

const textVariants = cva('font-normal', {
  variants: {
    as: {
      h1: 'text-h1-m lg:text-h1 font-semibold',
      h2: 'text-h2-m lg:text-h2 font-semibold',
      h3: 'text-h3-m lg:text-h3 font-semibold',
      h4: 'text-h4-m lg:text-h4 font-semibold',
      h5: 'text-h5-m lg:text-h5 font-semibold',
      span: '',
      p: 'text-p',
      div: '',
      li: '',
      label: 'text-label font-mono uppercase',
      pre: '',
      kbd: '',
      figcaption: '',
      time: ''
    },
    styleAs: {
      h1: 'text-h1-m lg:text-h1 font-semibold',
      h2: 'text-h2-m lg:text-h2 font-semibold',
      h3: 'text-h3-m lg:text-h3 font-semibold',
      h4: 'text-h4-m lg:text-h4 font-semibold',
      h5: 'text-h5-m lg:text-h5 font-semibold',
      'h5-small': 'text-h5-m lg:text-h5-m font-semibold',
      logo: 'text-logo font-semibold',
      'p-lg': 'text-p-lg',
      p: 'text-p',
      'p-sm': 'text-p-sm leading-3.5',
      'p-xs': 'text-p-xs leading-2.5',
      overline: 'text-overline font-mono uppercase',
      'label-sm': 'text-label-sm font-mono uppercase',
      label: 'text-label font-mono uppercase leading-normal',
      caption: 'text-caption font-mono',
      code: 'text-code font-mono',
      'code-sm': 'text-code-sm font-mono'
    }
  },
  defaultVariants: {
    as: 'p',
    styleAs: 'p'
  }
});

type AsElement = NonNullable<VariantProps<typeof textVariants>['as']>;

export type TextProps<T extends AsElement> = {
  className?: string;
  role?: string;
  children?: React.ReactNode;
} & VariantProps<typeof textVariants> &
  React.ComponentProps<T>;

/**
 * Convenience component to help apply the correct responsive styling to texts.
 *
 * In the nature design system, bolded fonts **always** use Cohere Variable. This behaviour
 * is reflected in `@cohere-ai/tailwind-themes/nature/fonts.css`.
 *
 * @param props.as - what HTML element it will render as
 * @param props.styleAs - what text styling will apply
 */
function Text<T extends AsElement>({
  as,
  styleAs,
  className,
  children,
  role,
  ref,
  ...props
}: TextProps<T>) {
  const renderAs: AsElement = as ?? 'p';
  const classes = cn(
    textVariants({
      ...(styleAs ? { styleAs } : { as: renderAs })
    }),
    className
  );

  return createElement(
    renderAs,
    {
      className: classes,
      role,
      dir: 'auto',
      ref,
      ...props
    },
    children
  );
}

export { Text, textVariants };
