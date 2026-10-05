// A README link pasted onto the site's root (cpuperf.com/#tlbs-page-walks-and-prefetchers)
// goes to the page that now carries that heading.
fetch("/anchors.json")
  .then((r) => r.json())
  .then((map) => {
    const target = map[decodeURIComponent(location.hash.slice(1))];
    if (target && target !== "/") location.replace(target);
  })
  .catch(() => {});
