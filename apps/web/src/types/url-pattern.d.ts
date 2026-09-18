import "urlpattern-polyfill";

declare global {
  type URLPatternInput = string | URLPatternInit;

  interface URLPatternOptions {
    ignoreCase?: boolean;
  }
}
