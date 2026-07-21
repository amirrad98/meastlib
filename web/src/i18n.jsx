import { createContext, useContext, useEffect, useMemo, useState } from "react";

const messages = {
  en: {
    library: "Middle East Digital Library", home: "Home", browse: "Browse", search: "Search",
    searchPlaceholder: "Search books, people, subjects, and full text", explore: "Explore the library",
    hero: "Read, search, and discover digitized Arabic and Persian books.", recentlyAdded: "Recently added",
    featuredCollections: "Collections", viewAll: "View all", noItems: "No items found.", loading: "Loading…",
    filters: "Filters", language: "Language", type: "Type", collection: "Collection", creator: "Creator",
    subject: "Subject", sort: "Sort", recent: "Recently added", title: "Title", date: "Date",
    dateFrom: "Date from", dateTo: "Date to", datePlaceholder: "Year or date", yearPlaceholder: "Year",
    relevance: "Relevance", all: "All", catalog: "Catalog only", fulltext: "Full text only",
    results: "results", works: "works", matchingPages: "matching pages", clear: "Clear filters",
    previous: "Previous", next: "Next", read: "Read", searchWithin: "Search within this book",
    aboutItem: "About this item", relatedVolumes: "Volumes in this collection", pages: "pages",
    machineText: "Searchable text was generated automatically and may contain errors.",
    bibliographic: "Bibliographic details", downloads: "Downloads", copyCitation: "Copy citation",
    citationCopied: "Citation copied", searchablePdf: "Searchable PDF", plainText: "Page text",
    alto: "ALTO XML", iiif: "IIIF manifest", page: "Page", go: "Go", thumbnails: "Pages",
    showText: "Show text", hideText: "Hide text", matchesInBook: "matches in this book",
    noResults: "No results matched your search.", tryAgain: "Try fewer words or remove a filter.",
    publicDomain: "Public domain", restricted: "Local access", admin: "Admin", publisher: "Publisher",
    edition: "Edition", copyFailed: "Could not copy the citation.",
  },
  fa: {
    library: "کتابخانهٔ دیجیتال خاورمیانه", home: "خانه", browse: "مرور آثار", search: "جستجو",
    searchPlaceholder: "جستجو در کتاب‌ها، نام‌ها، موضوع‌ها و متن کامل", explore: "کتابخانه را کاوش کنید",
    hero: "کتاب‌های دیجیتال فارسی و عربی را بخوانید، جستجو کنید و بیابید.", recentlyAdded: "تازه‌های کتابخانه",
    featuredCollections: "مجموعه‌ها", viewAll: "مشاهدهٔ همه", noItems: "اثری یافت نشد.", loading: "در حال بارگذاری…",
    filters: "فیلترها", language: "زبان", type: "نوع", collection: "مجموعه", creator: "پدیدآور",
    subject: "موضوع", sort: "ترتیب", recent: "تازه‌ترین", title: "عنوان", date: "تاریخ",
    dateFrom: "از تاریخ", dateTo: "تا تاریخ", datePlaceholder: "سال یا تاریخ", yearPlaceholder: "سال",
    relevance: "مرتبط‌ترین", all: "همه", catalog: "فقط فهرست", fulltext: "فقط متن کامل",
    results: "نتیجه", works: "اثر", matchingPages: "صفحهٔ منطبق", clear: "پاک کردن فیلترها",
    previous: "قبلی", next: "بعدی", read: "مطالعه", searchWithin: "جستجو در این کتاب",
    aboutItem: "دربارهٔ این اثر", relatedVolumes: "جلدهای این مجموعه", pages: "صفحه",
    machineText: "متن قابل جستجو به‌صورت خودکار تولید شده و ممکن است خطا داشته باشد.",
    bibliographic: "مشخصات کتاب‌شناختی", downloads: "دریافت", copyCitation: "رونوشت ارجاع",
    citationCopied: "ارجاع رونویسی شد", searchablePdf: "پی‌دی‌اف قابل جستجو", plainText: "متن صفحه",
    alto: "فایل ALTO", iiif: "نمایهٔ IIIF", page: "صفحه", go: "برو", thumbnails: "صفحه‌ها",
    showText: "نمایش متن", hideText: "پنهان کردن متن", matchesInBook: "نتیجه در این کتاب",
    noResults: "نتیجه‌ای برای این جستجو یافت نشد.", tryAgain: "واژه‌های کمتری بنویسید یا فیلتری را حذف کنید.",
    publicDomain: "مالکیت عمومی", restricted: "دسترسی محلی", admin: "مدیریت", publisher: "ناشر",
    edition: "ویرایش", copyFailed: "رونوشت ارجاع ممکن نشد.",
  },
};

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [locale, setLocale] = useState(() => localStorage.getItem("meastlib-locale") || "en");
  useEffect(() => localStorage.setItem("meastlib-locale", locale), [locale]);
  const value = useMemo(() => ({
    locale,
    dir: locale === "fa" ? "rtl" : "ltr",
    setLocale,
    t: (key) => messages[locale]?.[key] || messages.en[key] || key,
  }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
