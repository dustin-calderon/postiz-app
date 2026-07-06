'use client';

import React, {
  ChangeEvent,
  ClipboardEvent,
  FC,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Button } from '@gitroom/react/form/button';
import useSWR from 'swr';
import { useFetch } from '@gitroom/helpers/utils/custom.fetch';
import { hasExtension } from '@gitroom/helpers/utils/has.extension';
import { Media } from '@prisma/client';
import { useMediaDirectory } from '@gitroom/react/helpers/use.media.directory';
import { useSettings } from '@gitroom/frontend/components/launches/helpers/use.values';
import EventEmitter from 'events';
import { useToaster } from '@gitroom/react/toaster/toaster';
import clsx from 'clsx';
import { VideoFrame } from '@gitroom/react/helpers/video.frame';
import { useUppyUploader } from '@gitroom/frontend/components/media/new.uploader';
import dynamic from 'next/dynamic';
import { useUser } from '@gitroom/frontend/components/layout/user.context';
import { AiImage } from '@gitroom/frontend/components/launches/ai.image';
import { DropFiles } from '@gitroom/frontend/components/layout/drop.files';
import { deleteDialog } from '@gitroom/react/helpers/delete.dialog';
import { useT } from '@gitroom/react/translation/get.transation.service.client';
import { ThirdPartyMedia } from '@gitroom/frontend/components/third-parties/third-party.media';
import { ReactSortable } from 'react-sortablejs';
import { MediaComponentInner } from '@gitroom/frontend/components/launches/helpers/media.settings.component';
import { AiVideo } from '@gitroom/frontend/components/launches/ai.video';
import { useModals } from '@gitroom/frontend/components/layout/new-modal';
import { ThirdPartyMediaLibrary } from '@gitroom/frontend/components/third-parties/third-party.media-library';
import { Dashboard } from '@uppy/react';
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  PlusIcon,
  DeleteCircleIcon,
  CloseCircleIcon,
  DragHandleIcon,
  MediaSettingsIcon,
  InsertMediaIcon,
  DesignMediaIcon,
  VerticalDividerIcon,
  NoMediaIcon,
} from '@gitroom/frontend/components/ui/icons';
import { useLaunchStore } from '@gitroom/frontend/components/new-launch/store';
import { useShallow } from 'zustand/react/shallow';
import { LoadingComponent } from '@gitroom/frontend/components/layout/loading';
import { useDebounce } from 'use-debounce';
const Polonto = dynamic(
  () => import('@gitroom/frontend/components/launches/polonto')
);
const showModalEmitter = new EventEmitter();
export const Pagination: FC<{
  current: number;
  totalPages: number;
  setPage: (num: number) => void;
}> = (props) => {
  const t = useT();

  const { current, totalPages, setPage } = props;

  const paginationItems = useMemo(() => {
    // Convert to 1-based for algorithm (current is 0-based)
    const c = current + 1;
    const m = totalPages;

    // If total pages <= 10, show all pages
    if (m <= 10) {
      return Array.from({ length: m }, (_, i) => i + 1);
    }

    const delta = 3;
    const left = c - delta;
    const right = c + delta + 1;
    const range: number[] = [];
    const rangeWithDots: (number | '...')[] = [];
    let l: number | undefined;

    // Build the range of pages to show
    for (let i = 1; i <= m; i++) {
      if (i === 1 || i === m || (i >= left && i < right)) {
        range.push(i);
      }
    }

    // Add dots where there are gaps
    for (const i of range) {
      if (l !== undefined) {
        if (i - l === 2) {
          rangeWithDots.push(l + 1);
        } else if (i - l !== 1) {
          rangeWithDots.push('...');
        }
      }
      rangeWithDots.push(i);
      l = i;
    }

    // Limit to maximum 10 items by trimming pages near edges if needed
    while (rangeWithDots.length > 10) {
      const currentIndex = rangeWithDots.findIndex((item) => item === c);
      if (currentIndex !== -1 && currentIndex > rangeWithDots.length / 2) {
        // Current is in second half, remove one item from start side
        rangeWithDots.splice(2, 1);
      } else {
        // Current is in first half, remove one item from end side
        rangeWithDots.splice(-3, 1);
      }
    }

    return rangeWithDots;
  }, [current, totalPages]);

  return (
    <ul className="flex flex-row items-center gap-1 justify-center mt-[15px]">
      <li className={clsx(current === 0 && 'opacity-20 pointer-events-none')}>
        <div
          className="cursor-pointer inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 h-10 px-4 py-2 gap-1 ps-2.5 text-gray-400 hover:text-white border-[#1F1F1F] hover:bg-forth"
          aria-label="Go to previous page"
          onClick={() => setPage(current - 1)}
        >
          <ChevronLeftIcon className="lucide lucide-chevron-left h-4 w-4" />
          <span>{t('previous', 'Previous')}</span>
        </div>
      </li>
      {paginationItems.map((item, index) => (
        <li key={index}>
          {item === '...' ? (
            <span className="inline-flex items-center justify-center h-10 w-10 text-textColor select-none">
              ...
            </span>
          ) : (
            <div
              aria-current="page"
              onClick={() => setPage(item - 1)}
              className={clsx(
                'cursor-pointer inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 border hover:bg-forth h-10 w-10 hover:text-white border-newBorder',
                current === item - 1
                  ? 'bg-forth !text-white'
                  : 'text-textColor hover:text-white'
              )}
            >
              {item}
            </div>
          )}
        </li>
      ))}
      <li
        className={clsx(
          current + 1 === totalPages && 'opacity-20 pointer-events-none'
        )}
      >
        <a
          className="text-textColor hover:text-white group cursor-pointer inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 h-10 px-4 py-2 gap-1 pe-2.5 text-gray-400 border-[#1F1F1F] hover:bg-forth"
          aria-label="Go to next page"
          onClick={() => setPage(current + 1)}
        >
          <span>{t('next', 'Next')}</span>
          <ChevronRightIcon className="lucide lucide-chevron-right h-4 w-4" />
        </a>
      </li>
    </ul>
  );
};
export const ShowMediaBoxModal: FC = () => {
  const [showModal, setShowModal] = useState(false);
  const [callBack, setCallBack] =
    useState<(params: { id: string; path: string }[]) => void | undefined>();
  const closeModal = useCallback(() => {
    setShowModal(false);
    setCallBack(undefined);
  }, []);
  useEffect(() => {
    showModalEmitter.on('show-modal', (cCallback) => {
      setShowModal(true);
      setCallBack(() => cCallback);
    });
    return () => {
      showModalEmitter.removeAllListeners('show-modal');
    };
  }, []);
  if (!showModal) return null;
  return (
    <div className="text-textColor">
      <MediaBox setMedia={callBack!} closeModal={closeModal} />
    </div>
  );
};
export const showMediaBox = (
  callback: (params: { id: string; path: string }) => void
) => {
  showModalEmitter.emit('show-modal', callback);
};
const CHUNK_SIZE = 1024 * 1024;
const MAX_UPLOAD_SIZE = 1024 * 1024 * 1024; // 1 GB
export const MediaBox: FC<{
  setMedia: (params: { id: string; path: string }[]) => void;
  standalone?: boolean;
  type?: 'image' | 'video';
  closeModal: () => void;
}> = ({ type, standalone, setMedia }) => {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebounce(search, 300);
  /** `undefined` = all media. `'__root__'` = unfoldered. A name = that folder. */
  const [activeFolder, setActiveFolder] = useState<string | undefined>(undefined);
  const [newFolderName, setNewFolderName] = useState('');
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [selectedForMove, setSelectedForMove] = useState<string[]>([]);
  const [showMoveMenu, setShowMoveMenu] = useState<boolean>(false);
  /**
   * Holds the name of a newly created folder that has not yet been populated.
   * Appears as a dashed tab in the strip; persisted only after first item is moved in.
   */
  const [pendingFolderName, setPendingFolderName] = useState<string | null>(null);
  /** Grid/list view toggle — session preference only, not persisted. */
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  /** Zoom: number of columns in the grid. Maps to ZOOM_LEVELS indices. */
  const ZOOM_LEVELS = [3, 4, 5, 6, 8, 10] as const;
  type ZoomLevel = typeof ZOOM_LEVELS[number];
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>(6);
  /** Sidebar visibility — collapsed by default in standalone (modal) mode. */
  const [sidebarOpen, setSidebarOpen] = useState(!standalone);
  /** Set of brand-level paths (first path segment) that are expanded in the tree. */
  const [expandedBrands, setExpandedBrands] = useState<Set<string>>(new Set());
  const fetch = useFetch();
  const modals = useModals();
  const toaster = useToaster();
  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, activeFolder]);
  const loadMedia = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page + 1) });
    if (debouncedSearch.trim()) {
      params.set('search', debouncedSearch.trim());
    }
    if (activeFolder !== undefined) {
      params.set('folder', activeFolder);
    }
    return (await fetch(`/media?${params.toString()}`)).json();
  }, [page, debouncedSearch, activeFolder]);
  const { data, mutate, isLoading } = useSWR(
    `get-media-${page}-${debouncedSearch}-${activeFolder ?? 'all'}`,
    loadMedia
  );
  const loadFolders = useCallback(async () => {
    return (await fetch('/media/folders')).json() as Promise<string[]>;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetch]);
  const { data: folders = [], mutate: mutateFolders } = useSWR(
    'get-media-folders',
    loadFolders
  );
  const [selected, setSelected] = useState([]);
  const t = useT();
  const uploaderRef = useRef<any>(null);
  const mediaDirectory = useMediaDirectory();
  const [loading, setLoading] = useState(false);

  const createFolder = useCallback(async () => {
    const trimmed = newFolderName.trim();
    if (!trimmed) return;
    /**
     * Folders are virtual: they materialise in the DB the moment at least one
     * media item is moved into them (via moveToFolder). Here we only set the
     * pending state with the correct path:
     *   - If activeFolder is a folder path → create as child: "Brand/NewSub"
     *   - If activeFolder is undefined or '__root__' → create as brand-level
     *
     * The pending folder appears in the sidebar with a dashed style until
     * the user moves at least one item into it.
     */
    const parentPath =
      activeFolder && activeFolder !== '__root__'
        ? activeFolder.split('/')[0] // always parent at brand level
        : undefined;
    const fullPath = parentPath ? `${parentPath}/${trimmed}` : trimmed;
    setPendingFolderName(fullPath);
    // Auto-expand the parent brand in the sidebar tree.
    if (parentPath) {
      setExpandedBrands((prev) => new Set(prev).add(parentPath));
    }
    setNewFolderName('');
    setCreatingFolder(false);
  }, [newFolderName, activeFolder]);

  const moveToFolder = useCallback(
    async (mediaIds: string[], folder: string | null) => {
      try {
        await fetch('/media/move', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: mediaIds, folder }),
        });
        // Refresh both the media list and the folder tab strip atomically.
        // mutateFolders() is critical: it makes newly populated folders
        // appear in the tab bar on the next render.
        await Promise.all([mutate(), mutateFolders()]);
        setSelectedForMove([]);
        setShowMoveMenu(false);
        // If items were moved into the pending (new) folder, it now exists in
        // the DB — clear the pending state and navigate to the folder tab.
        if (folder !== null && folder === pendingFolderName) {
          setPendingFolderName(null);
          setActiveFolder(folder);
        }
      } catch (err) {
        console.error('[MediaBox] moveToFolder failed:', err);
        toaster.show(t('move_failed', 'Failed to move items. Please try again.'), 'warning');
      }
    },
    [fetch, mutate, mutateFolders, pendingFolderName, toaster, t]
  );

  const renameFolderHandler = useCallback(
    async (oldPath: string) => {
      // Prompt shows only the last segment (leaf name) for a cleaner UX.
      const leafName = oldPath.split('/').pop() ?? oldPath;
      const newLeaf = window.prompt(
        t('rename_folder_prompt', 'New folder name:'),
        leafName
      );
      if (!newLeaf) return;
      const trimmedNew = newLeaf.trim();
      if (!trimmedNew || trimmedNew === leafName) return;
      // Reconstruct the full new path by replacing only the last segment.
      const segments = oldPath.split('/');
      segments[segments.length - 1] = trimmedNew;
      const newPath = segments.join('/');
      try {
        await fetch('/media/rename-folder', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ oldName: oldPath, newName: newPath }),
        });
        // If the user is currently viewing the renamed folder (or a sub-path of
        // it), update activeFolder to the new path so the SWR key stays valid.
        if (activeFolder && activeFolder.startsWith(oldPath)) {
          setActiveFolder(activeFolder.replace(oldPath, newPath));
        }
        await Promise.all([mutateFolders(), mutate()]);
      } catch (err) {
        console.error('[MediaBox] renameFolderHandler failed:', err);
        toaster.show(t('rename_failed', 'Failed to rename folder. Please try again.'), 'warning');
      }
    },
    [fetch, activeFolder, mutateFolders, mutate, toaster, t]
  );

  /** Ref tracking activeFolder — read lazily by the Uppy file-added handler. */
  const activeFolderRef = useRef<string | undefined>(activeFolder);
  useEffect(() => {
    activeFolderRef.current = activeFolder;
  }, [activeFolder]);

  const uppy = useUppyUploader({
    allowedFileTypes:
      type == 'image'
        ? 'image/*'
        : type == 'video'
        ? 'video/*'
        : 'image/*,video/*',
    folderRef: activeFolderRef,
    onUploadSuccess: async (arr) => {
      await mutate();
      if (standalone) {
        return;
      }
      setSelected((prevSelected) => {
        return [...prevSelected, ...arr];
      });
    },
    onStart: () => setLoading(true),
    onEnd: () => setLoading(false),
  });

  const addRemoveSelected = useCallback(
    (media: any) => () => {
      if (standalone) {
        return;
      }
      const exists = selected.find((p: any) => p.id === media.id);
      if (exists) {
        setSelected(selected.filter((f: any) => f.id !== media.id));
        return;
      }
      setSelected([...selected, media]);
    },
    [selected]
  );

  const addMedia = useCallback(async () => {
    if (standalone) {
      return;
    }
    // @ts-ignore
    setMedia(selected);
    modals.closeCurrent();
  }, [selected]);

  const addToUpload = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      const totalSize = files.reduce((acc, file) => acc + file.size, 0);

      if (totalSize > MAX_UPLOAD_SIZE) {
        toaster.show(
          t(
            'upload_size_limit_exceeded',
            'Upload size limit exceeded. Maximum 1 GB per upload session.'
          ),
          'warning'
        );
        return;
      }

      setLoading(true);

      // @ts-ignore
      uppy.addFiles(files);
    },
    [toaster, t]
  );

  const dragAndDrop = useCallback(
    async (event: ClipboardEvent<HTMLDivElement> | File[]) => {
      // @ts-ignore
      const clipboardItems = event.map((p) => ({
        kind: 'file',
        getAsFile: () => p,
      }));
      if (!clipboardItems) {
        return;
      }

      const files: File[] = [];
      // @ts-ignore
      for (const item of clipboardItems) {
        if (item.kind === 'file') {
          const file = item.getAsFile();
          if (file) {
            files.push(file);
          }
        }
      }

      const totalSize = files.reduce((acc, file) => acc + file.size, 0);

      if (totalSize > MAX_UPLOAD_SIZE) {
        toaster.show(
          t(
            'upload_size_limit_exceeded',
            'Upload size limit exceeded. Maximum 1 GB per upload session.'
          ),
          'warning'
        );
        return;
      }

      setLoading(true);

      for (const file of files) {
        uppy.addFile(file);
      }
    },
    [toaster, t]
  );

  const maximize = useCallback(
    (media: Media) => async (e: any) => {
      e.stopPropagation();
      modals.openModal({
        title: '',
        top: 10,
        children: (
          <div className="w-full h-full p-[50px]">
            {hasExtension(media.path, 'mp4') ? (
              <VideoFrame
                autoplay={true}
                url={mediaDirectory.set(media.path)}
              />
            ) : (
              <img
                width="100%"
                height="100%"
                className="w-full h-full max-h-[100%] max-w-[100%] object-cover"
                src={mediaDirectory.set(media.path)}
                alt="media"
              />
            )}
          </div>
        ),
      });
    },
    []
  );

  const deleteImage = useCallback(
    (media: Media) => async (e: any) => {
      e.stopPropagation();
      if (
        !(await deleteDialog(
          t(
            'are_you_sure_you_want_to_delete_the_image',
            'Are you sure you want to delete the image?'
          )
        ))
      ) {
        return;
      }
      await fetch(`/media/${media.id}`, {
        method: 'DELETE',
      });
      mutate();
    },
    [mutate]
  );

  const btn = useMemo(() => {
    return (
      <button
        disabled={loading}
        onClick={() => uploaderRef?.current?.click()}
        className="relative cursor-pointer bg-btnSimple changeColor flex gap-[8px] h-[44px] px-[18px] justify-center items-center rounded-[8px]"
      >
        {loading ? (
          <div className="absolute left-[50%] top-[50%] -translate-y-[50%] -translate-x-[50%]">
            <div className="animate-spin h-[20px] w-[20px] border-4 border-white border-t-transparent rounded-full" />
          </div>
        ) : (
          <PlusIcon size={14} />
        )}
        <div className={loading ? 'invisible' : undefined}>{t('upload', 'Upload')}</div>
      </button>
    );
  }, [t, loading]);

  return (
    <DropFiles disabled={loading} className="flex flex-col flex-1" onDrop={dragAndDrop}>
      {/* ── Root layout: sidebar + content ── */}
      <div className="flex flex-1 gap-0 min-h-0">

        {/* ════════════════════════════════════════════
            Collapsible folder sidebar
            - parseFolderTree builds a 2-level tree from string[]
            - Brand node: click navigates, chevron toggles expansion
            - Sub-folder node: click navigates directly
            ════════════════════════════════════════════ */}
        {(() => {
          /**
           * Builds a 2-level folder tree from the flat string[] returned by
           * GET /media/folders. Paths use "/" as separator.
           *
           * Input:  ["AmoRismo", "Citem", "Citem/Diseños", "Citem/Eventos"]
           * Output: [{ name:"AmoRismo", path:"AmoRismo", children:[] },
           *          { name:"Citem",    path:"Citem",    children:[
           *            { name:"Diseños", path:"Citem/Diseños" },
           *            { name:"Eventos", path:"Citem/Eventos" }
           *          ]}]
           */
          interface FolderNode { name: string; path: string; children: FolderNode[]; }
          const tree: FolderNode[] = [];
          const map: Record<string, FolderNode> = {};

          // Sort to guarantee parents appear before children when iterating
          const sorted = [...(folders as string[])].sort();
          for (const path of sorted) {
            const segments = path.split('/');
            const name = segments[segments.length - 1];
            const node: FolderNode = { name, path, children: [] };
            map[path] = node;
            if (segments.length === 1) {
              tree.push(node);
            } else {
              // Find or create the parent brand node (we only support 2 levels
              // in the UI tree; deeper paths appear under the brand).
              const parentPath = segments[0];
              if (!map[parentPath]) {
                const parentNode: FolderNode = { name: parentPath, path: parentPath, children: [] };
                map[parentPath] = parentNode;
                tree.push(parentNode);
              }
              map[parentPath].children.push(node);
            }
          }

          // Merge pending folder into the tree for display (without DB presence).
          if (pendingFolderName) {
            const segs = pendingFolderName.split('/');
            if (segs.length === 1 && !map[pendingFolderName]) {
              // Brand-level pending: add at end of tree
              tree.push({ name: pendingFolderName, path: pendingFolderName, children: [], });
            } else if (segs.length > 1) {
              const parentPath = segs[0];
              if (map[parentPath]) {
                const alreadyIn = map[parentPath].children.some(c => c.path === pendingFolderName);
                if (!alreadyIn) {
                  map[parentPath].children.push({ name: segs[segs.length - 1], path: pendingFolderName, children: [] });
                }
              }
            }
          }

          const itemCls = (path: string) =>
            clsx(
              'flex items-center w-full px-[10px] h-[30px] rounded-[6px] text-[12px] font-[500] transition-colors cursor-pointer group/item',
              activeFolder === path
                ? 'bg-[#612BD3] text-white'
                : 'text-textColor hover:bg-[#612BD3]/10'
            );

          const renderNode = (node: FolderNode, depth = 0) => {
            const isBrand = depth === 0;
            const isExpanded = expandedBrands.has(node.path);
            const isPending = node.path === pendingFolderName;
            const hasChildren = node.children.length > 0;

            return (
              <div key={node.path}>
                <div
                  className={clsx(
                    itemCls(node.path),
                    isPending && 'border border-dashed border-[#612BD3]/60 opacity-80',
                    depth > 0 && 'pl-[22px]'
                  )}
                >
                  {/* Chevron toggle (only for brand-level nodes with children) */}
                  {isBrand && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedBrands((prev) => {
                          const next = new Set(prev);
                          next.has(node.path) ? next.delete(node.path) : next.add(node.path);
                          return next;
                        });
                      }}
                      className="mr-[4px] w-[14px] h-[14px] flex items-center justify-center flex-shrink-0 opacity-60 hover:opacity-100"
                    >
                      {hasChildren ? (isExpanded ? '▼' : '▶') : <span className="w-[14px]" />}
                    </button>
                  )}
                  {/* Folder icon */}
                  <span className="mr-[6px] text-[11px] flex-shrink-0">
                    {isPending ? '✨' : isBrand ? '🗂' : '📁'}
                  </span>
                  {/* Folder name — navigates on click */}
                  <button
                    className="flex-1 text-left truncate"
                    onClick={() => {
                      setActiveFolder(node.path);
                      // Auto-expand brand when navigating into it or its children
                      if (isBrand) setExpandedBrands((prev) => new Set(prev).add(node.path));
                    }}
                  >
                    {node.name}
                  </button>
                  {/* Context actions: rename + add sub-folder (shown on hover, not for pending) */}
                  {!isPending && (
                    <div className="hidden group-hover/item:flex items-center gap-[2px] flex-shrink-0">
                      {isBrand && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveFolder(node.path);
                            setExpandedBrands((prev) => new Set(prev).add(node.path));
                            setCreatingFolder(true);
                          }}
                          className="w-[16px] h-[16px] flex items-center justify-center text-[10px] rounded hover:text-[#a78bfa]"
                          title={t('add_subfolder', 'Add sub-folder')}
                        >+</button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); renameFolderHandler(node.path); }}
                        className="w-[16px] h-[16px] flex items-center justify-center text-[10px] rounded hover:text-[#a78bfa]"
                        title={t('rename_folder', 'Rename')}
                      >✎</button>
                    </div>
                  )}
                  {/* Discard button for pending folder */}
                  {isPending && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setPendingFolderName(null);
                        if (activeFolder === pendingFolderName) setActiveFolder(undefined);
                      }}
                      className="w-[14px] h-[14px] flex items-center justify-center text-[10px] flex-shrink-0 hover:text-red-400"
                      title={t('discard_folder', 'Discard')}
                    >✕</button>
                  )}
                </div>
                {/* Render children when brand is expanded */}
                {isBrand && isExpanded && node.children.map((child) => renderNode(child, 1))}
              </div>
            );
          };

          return (
            <>
              {/* Sidebar toggle button — always visible */}
              <button
                onClick={() => setSidebarOpen((p) => !p)}
                className="flex-shrink-0 self-start mt-[7px] mr-[4px] w-[22px] h-[22px] flex items-center justify-center rounded-[4px] text-[11px] text-textColor bg-newColColor hover:bg-[#612BD3]/20 transition-colors"
                title={sidebarOpen ? t('collapse_sidebar', 'Collapse folders') : t('expand_sidebar', 'Expand folders')}
              >
                {sidebarOpen ? '◀' : '▶'}
              </button>

              {sidebarOpen && (
                <div className="w-[176px] flex-shrink-0 flex flex-col gap-[2px] pr-[8px] border-r border-newColColor/30 mr-[12px] overflow-y-auto scrollbar scrollbar-thumb-newColColor scrollbar-track-transparent max-h-full">
                  {/* Static entries */}
                  <button
                    onClick={() => setActiveFolder(undefined)}
                    className={itemCls(undefined as any).replace('undefined', activeFolder === undefined ? 'bg-[#612BD3] text-white' : '')}
                  >
                    <span className="mr-[6px] text-[11px]">📋</span>
                    {t('all', 'All media')}
                  </button>
                  <button
                    onClick={() => setActiveFolder('__root__')}
                    className={clsx(
                      'flex items-center w-full px-[10px] h-[30px] rounded-[6px] text-[12px] font-[500] transition-colors cursor-pointer',
                      activeFolder === '__root__'
                        ? 'bg-[#612BD3] text-white'
                        : 'text-textColor hover:bg-[#612BD3]/10'
                    )}
                  >
                    <span className="mr-[6px] text-[11px]">📎</span>
                    {t('no_folder', 'No folder')}
                  </button>

                  {/* Separator */}
                  {tree.length > 0 && <div className="border-t border-newColColor/30 my-[4px]" />}

                  {/* Folder tree */}
                  {tree.map((node) => renderNode(node, 0))}

                  {/* New folder inline input or button */}
                  <div className="border-t border-newColColor/30 mt-[4px] pt-[4px]">
                    {!creatingFolder ? (
                      <button
                        onClick={() => setCreatingFolder(true)}
                        className="flex items-center gap-[4px] w-full px-[10px] h-[30px] rounded-[6px] text-[12px] font-[500] text-textColor hover:bg-[#612BD3]/10 transition-colors"
                      >
                        <PlusIcon size={10} />
                        {activeFolder && activeFolder !== '__root__'
                          ? t('new_subfolder', 'New sub-folder')
                          : t('new_brand', 'New brand')}
                      </button>
                    ) : (
                      <div className="flex flex-col gap-[4px] px-[4px]">
                        <input
                          autoFocus
                          value={newFolderName}
                          onChange={(e) => setNewFolderName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') createFolder();
                            if (e.key === 'Escape') { setCreatingFolder(false); setNewFolderName(''); }
                          }}
                          placeholder={
                            activeFolder && activeFolder !== '__root__'
                              ? t('subfolder_name', 'Sub-folder name…')
                              : t('brand_name', 'Brand name…')
                          }
                          className="h-[28px] px-[8px] rounded-[6px] bg-newBgColorInner border border-newColColor text-[12px] outline-none focus:border-[#612BD3]"
                        />
                        <div className="flex gap-[4px]">
                          <button
                            onClick={createFolder}
                            className="flex-1 h-[24px] rounded-[4px] bg-[#612BD3] text-white text-[11px] font-[600]"
                          >
                            {t('create', 'Create')}
                          </button>
                          <button
                            onClick={() => { setCreatingFolder(false); setNewFolderName(''); }}
                            className="h-[24px] px-[8px] rounded-[4px] bg-newColColor text-textColor text-[11px]"
                          >✕</button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          );
        })()}

        {/* ════════════════════════════════════════════
            Right column: toolbar + bulk move bar + media grid
            ════════════════════════════════════════════ */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* ── Toolbar: search + view toggle + zoom + upload ── */}
          <div
            className={clsx(
              'flex items-center gap-[12px] mb-[10px]',
              !isLoading && !data?.results?.length && !debouncedSearch && 'hidden'
            )}
          >
            <div className="flex-1">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('search_media_by_name', 'Search by file name')}
                className="w-full h-[44px] px-[14px] rounded-[8px] bg-newBgColorInner border border-newColColor text-[14px] outline-none focus:border-[#612BD3]"
              />
            </div>
            <input
              type="file"
              ref={uploaderRef}
              onChange={addToUpload}
              className="hidden"
              multiple={true}
            />
            <div className="flex items-center gap-[8px]">
              {/* View toggle */}
              <div className="flex items-center rounded-[6px] border border-newColColor overflow-hidden">
                <button
                  onClick={() => setViewMode('grid')}
                  className={clsx('px-[8px] h-[30px] text-[14px] transition-colors', viewMode === 'grid' ? 'bg-[#612BD3] text-white' : 'text-textColor hover:bg-[#612BD3]/20')}
                  title="Vista de cuadrícula"
                >⊞</button>
                <button
                  onClick={() => setViewMode('list')}
                  className={clsx('px-[8px] h-[30px] text-[14px] transition-colors', viewMode === 'list' ? 'bg-[#612BD3] text-white' : 'text-textColor hover:bg-[#612BD3]/20')}
                  title="Vista de lista"
                >≡</button>
              </div>
              {/* Zoom controls — grid mode only */}
              {viewMode === 'grid' && (
                <div className="flex items-center gap-[4px]">
                  <button
                    onClick={() => setZoomLevel((prev) => { const idx = ZOOM_LEVELS.indexOf(prev); return ZOOM_LEVELS[Math.max(0, idx - 1)]; })}
                    disabled={zoomLevel === ZOOM_LEVELS[0]}
                    className="px-[6px] h-[30px] rounded-[6px] bg-newColColor text-textColor disabled:opacity-30 hover:bg-[#612BD3]/20"
                    title="Menos archivos, más grandes"
                  >−</button>
                  <input
                    type="range"
                    min={0}
                    max={ZOOM_LEVELS.length - 1}
                    value={ZOOM_LEVELS.indexOf(zoomLevel)}
                    onChange={(e) => setZoomLevel(ZOOM_LEVELS[Number(e.target.value)] as ZoomLevel)}
                    className="w-[70px] accent-[#612BD3]"
                  />
                  <button
                    onClick={() => setZoomLevel((prev) => { const idx = ZOOM_LEVELS.indexOf(prev); return ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, idx + 1)]; })}
                    disabled={zoomLevel === ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}
                    className="px-[6px] h-[30px] rounded-[6px] bg-newColColor text-textColor disabled:opacity-30 hover:bg-[#612BD3]/20"
                    title="Más archivos, más pequeños"
                  >+</button>
                </div>
              )}
              {btn}
              <ThirdPartyMediaLibrary onImported={() => mutate()} />
            </div>
          </div>

          {/* ── Bulk move bar ── */}
          {selectedForMove.length > 0 && (
            <div className="flex items-center gap-[6px] flex-wrap mb-[8px]">
              <span className="text-[12px] text-textColor">
                {selectedForMove.length} {t('selected', 'selected')}
              </span>
              <div className="relative ml-auto flex items-center gap-[6px]">
                <button
                  onClick={() => setShowMoveMenu((prev) => !prev)}
                  className="px-[10px] h-[30px] rounded-[6px] bg-newColColor text-textColor text-[12px] font-[600] hover:bg-[#612BD3]/20"
                >
                  {t('move_to', 'Move to…')}
                </button>
                {showMoveMenu && (() => {
                  // Build move-to tree from same data — reuse the folders SWR array.
                  // Renders as an indented list: brand level + sub-folder level.
                  interface MoveNode { name: string; path: string; children: MoveNode[]; }
                  const moveTree: MoveNode[] = [];
                  const moveMap: Record<string, MoveNode> = {};
                  const allPaths = [
                    ...(folders as string[]),
                    ...(pendingFolderName && !(folders as string[]).includes(pendingFolderName) ? [pendingFolderName] : []),
                  ].sort();
                  for (const p of allPaths) {
                    const segs = p.split('/');
                    const node: MoveNode = { name: segs[segs.length - 1], path: p, children: [] };
                    moveMap[p] = node;
                    if (segs.length === 1) {
                      moveTree.push(node);
                    } else {
                      const parentPath = segs[0];
                      if (!moveMap[parentPath]) {
                        const pNode: MoveNode = { name: parentPath, path: parentPath, children: [] };
                        moveMap[parentPath] = pNode;
                        moveTree.push(pNode);
                      }
                      moveMap[parentPath].children.push(node);
                    }
                  }

                  const renderMoveNode = (node: MoveNode, depth = 0): React.ReactNode => (
                    <Fragment key={node.path}>
                      <button
                        onClick={() => moveToFolder(selectedForMove, node.path)}
                        className="w-full text-left px-[12px] py-[5px] text-[12px] text-textColor hover:bg-newColColor flex items-center gap-[4px]"
                        style={{ paddingLeft: `${12 + depth * 14}px` }}
                      >
                        <span className="text-[10px]">{node.path === pendingFolderName ? '✨' : depth === 0 ? '🗂' : '📁'}</span>
                        {node.name}
                      </button>
                      {node.children.map((c) => renderMoveNode(c, depth + 1))}
                    </Fragment>
                  );

                  return (
                    <div className="absolute top-[34px] right-0 z-[200] bg-newBgColorInner border border-newColColor rounded-[8px] shadow-xl min-w-[180px] py-[4px] max-h-[300px] overflow-y-auto">
                      <button
                        onClick={() => moveToFolder(selectedForMove, null)}
                        className="w-full text-left px-[12px] py-[5px] text-[12px] text-textColor hover:bg-newColColor flex items-center gap-[4px]"
                      >
                        <span className="text-[10px]">📎</span>
                        {t('no_folder', 'No folder (root)')}
                      </button>
                      {moveTree.length > 0 && <div className="border-t border-newColColor/30 my-[2px]" />}
                      {moveTree.map((n) => renderMoveNode(n, 0))}
                    </div>
                  );
                })()}
                <button
                  onClick={() => setSelectedForMove([])}
                  className="px-[8px] h-[30px] rounded-[6px] bg-newColColor text-textColor text-[12px] hover:text-white"
                >✕</button>
              </div>
            </div>
          )}

          {/* ── Uppy progress bar ── */}
          <div className="w-full pointer-events-none relative mt-[5px] mb-[5px]">
            <div className="w-full h-[46px] overflow-hidden absolute left-0 bg-newBgColorInner uppyChange">
              <Dashboard
                height={46}
                uppy={uppy}
                id={`uploader`}
                showProgressDetails={true}
                hideUploadButton={true}
                hideRetryButton={true}
                hidePauseResumeButton={true}
                hideCancelButton={true}
                hideProgressAfterFinish={true}
              />
            </div>
            <div className="w-full h-[46px] uppyChange" />
          </div>

          {/* ── Media area ── */}
          <div
            className={clsx(
              'flex-1 relative',
              !isLoading && !data?.results?.length && 'bg-newTextColor/[0.02] rounded-[12px]'
            )}
          >
            <div
              className={clsx(
                'absolute -left-[3px] -top-[3px] withp3 h-full overflow-x-hidden overflow-y-auto scrollbar scrollbar-thumb-newColColor scrollbar-track-newBgColorInner',
                !isLoading && !data?.results?.length && 'flex justify-center items-center gap-[20px] flex-col'
              )}
            >

            {!isLoading && !data?.results?.length && (
              <>
                {/* ── Contextual empty state for pending folder ── */}
                {activeFolder === pendingFolderName && pendingFolderName ? (
                  <>
                    <div className="text-[40px] opacity-30">📂</div>
                    <div className="text-[20px] font-[600]">Esta carpeta está vacía</div>
                    <div className="text-[13px] text-textColor/60 text-center">
                      Selecciona archivos con los checkboxes y usa &ldquo;Move to…&rdquo; para añadirlos aquí.
                    </div>
                  </>
                ) : (
                  <>
                    <NoMediaIcon />
                    <div className="text-[20px] font-[600]">
                      {debouncedSearch
                        ? t('no_media_match_search', 'No media matches your search')
                        : t('you_dont_have_any_media_yet', "You don't have any media yet")}
                    </div>
                    <div className="whitespace-pre-line text-newTextColor/[0.6] text-center">
                      {t('select_or_upload_pictures_max_1gb', 'Select or upload pictures (maximum 1 GB per upload).')}{' '}
                      {'\n'}
                      {t('you_can_drag_drop_pictures', 'You can also drag & drop pictures.')}
                    </div>
                    <div className="forceChange flex gap-[8px]">
                      {btn}
                      <ThirdPartyMediaLibrary onImported={() => mutate()} />
                    </div>
                  </>
                )}
              </>
            )}
            {/* ── Grid skeleton ── */}
            {isLoading && viewMode === 'grid' && (
              <>
                {[...new Array(16)].map((_, i) => (
                  <div
                    style={{ width: `calc(100% / ${zoomLevel})`, maxWidth: `calc(100% / ${zoomLevel})` }}
                    className="px-[3px] py-[3px] float-left rounded-[6px] cursor-pointer aspect-square"
                    key={i}
                  >
                    <div className="w-full h-full bg-newSep rounded-[6px] animate-pulse" />
                  </div>
                ))}
              </>
            )}
            {/* ── List skeleton ── */}
            {isLoading && viewMode === 'list' && (
              <>
                {[...new Array(8)].map((_, i) => (
                  <div key={i} className="flex items-center gap-[12px] h-[52px] px-[8px] w-full">
                    <div className="w-[40px] h-[40px] bg-newSep rounded-[4px] animate-pulse flex-shrink-0" />
                    <div className="flex-1 h-[12px] bg-newSep rounded animate-pulse" />
                    <div className="w-[80px] h-[12px] bg-newSep rounded animate-pulse" />
                  </div>
                ))}
              </>
            )}
            {/* ── Grid view ── */}
            {viewMode === 'grid' && data?.results
              ?.filter((f: any) => {
                if (type === 'video') return hasExtension(f.path, 'mp4');
                if (type === 'image') return !hasExtension(f.path, 'mp4');
                return true;
              })
              .map((media: any) => (
                <div
                  style={{ width: `calc(100% / ${zoomLevel})`, maxWidth: `calc(100% / ${zoomLevel})` }}
                  className={clsx('group px-[3px] py-[3px] float-left rounded-[6px] aspect-square', !standalone && 'cursor-pointer')}
                  key={media.id}
                >
                  <div
                    className={clsx(
                      'w-full h-full rounded-[6px] border-[4px] relative',
                      !!selected.find((p) => p.id === media.id)
                        ? 'border-[#612BD3]'
                        : 'border-transparent'
                    )}
                    onClick={addRemoveSelected(media)}
                  >
                    {!!selected.find((p: any) => p.id === media.id) ? (
                      <div className="text-white flex z-[101] justify-center items-center text-[14px] font-[500] w-[24px] h-[24px] rounded-full bg-[#612BD3] absolute -bottom-[10px] -end-[10px]">
                        {selected.findIndex((z: any) => z.id === media.id) + 1}
                      </div>
                    ) : (
                      <DeleteCircleIcon
                        className="cursor-pointer hidden z-[100] group-hover:block absolute -top-[5px] -end-[5px]"
                        onClick={deleteImage(media)}
                      />
                    )}
                    {/* Move-to-folder checkbox — top-left, appears on hover */}
                    <input
                      type="checkbox"
                      checked={selectedForMove.includes(media.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        setSelectedForMove((prev) =>
                          prev.includes(media.id)
                            ? prev.filter((id) => id !== media.id)
                            : [...prev, media.id]
                        );
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className={clsx(
                        'absolute top-[2px] start-[2px] z-[101] w-[16px] h-[16px] cursor-pointer accent-[#612BD3]',
                        selectedForMove.includes(media.id)
                          ? 'opacity-100' // always visible when checked
                          : 'opacity-0 group-hover:opacity-100'
                      )}
                      title={t('select_for_move', 'Select to move to folder')}
                    />
                    {media.folder && (
                      <div className="absolute top-[2px] end-[2px] z-[100] text-[9px] bg-black/50 text-white px-[4px] py-[1px] rounded-[3px] max-w-[80px] truncate">
                        {media.folder}
                      </div>
                    )}
                    <div className="absolute bottom-[10px] end-[10px] z-[100]">{media.originalName}</div>
                    <div className="w-full h-full rounded-[6px] overflow-hidden relative">
                      <div className="absolute z-[20] left-[50%] top-[50%] -translate-x-[50%] -translate-y-[50%]">
                        <div
                          onClick={maximize(media)}
                          className="cursor-pointer p-[4px] bg-black/40 hidden group-hover:block hover:scale-150 transition-all"
                        >
                          <svg
                            width="30"
                            height="30"
                            viewBox="0 0 14 14"
                            fill="none"
                            xmlns="http://www.w3.org/2000/svg"
                          >
                            <path
                              d="M2 9H0V14H5V12H2V9ZM0 5H2V2H5V0H0V5ZM12 12H9V14H14V9H12V12ZM9 0V2H12V5H14V0H9Z"
                              fill="#F1F5F9"
                            />
                          </svg>
                        </div>
                      </div>
                      {hasExtension(media.path, 'mp4') ? (
                        <VideoFrame url={mediaDirectory.set(media.path)} />
                      ) : (
                        <img
                          width="100%"
                          height="100%"
                          className="w-full h-full object-cover"
                          src={mediaDirectory.set(media.path)}
                          alt="media"
                        />
                      )}
                    </div>
                  </div>
                </div>
              ))}
            {/* ── List view ── */}
            {viewMode === 'list' && !isLoading && (
              <div className="flex flex-col w-full divide-y divide-newColColor/30">
                {data?.results
                  ?.filter((f: any) => {
                    if (type === 'video') return hasExtension(f.path, 'mp4');
                    if (type === 'image') return !hasExtension(f.path, 'mp4');
                    return true;
                  })
                  .map((media: any) => (
                    <div
                      key={media.id}
                      className="flex items-center gap-[12px] h-[52px] px-[8px] hover:bg-newColColor/10 group/row cursor-pointer"
                      onClick={addRemoveSelected(media)}
                    >
                      <input
                        type="checkbox"
                        checked={selectedForMove.includes(media.id)}
                        onChange={(e) => {
                          e.stopPropagation();
                          setSelectedForMove((prev) =>
                            prev.includes(media.id)
                              ? prev.filter((id) => id !== media.id)
                              : [...prev, media.id]
                          );
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-[14px] h-[14px] cursor-pointer accent-[#612BD3] flex-shrink-0"
                      />
                      <div className="w-[40px] h-[40px] rounded-[4px] overflow-hidden flex-shrink-0">
                        {hasExtension(media.path, 'mp4')
                          ? <VideoFrame url={mediaDirectory.set(media.path)} />
                          : <img src={mediaDirectory.set(media.path)} className="w-full h-full object-cover" alt="media" />}
                      </div>
                      <span className="flex-1 text-[13px] truncate">{media.originalName}</span>
                      <span className="w-[100px] text-[12px] text-textColor/60 truncate">{media.folder ?? '—'}</span>
                      <span className="w-[36px] text-[11px] text-textColor/50 uppercase">
                        {hasExtension(media.path, 'mp4') ? 'vid' : 'img'}
                      </span>
                      <button
                        onClick={deleteImage(media)}
                        className="hidden group-hover/row:block text-red-400 text-[12px] flex-shrink-0"
                      >✕</button>
                    </div>
                  ))}
              </div>
            )}
          </div>
          {/* end scrollable inner div */}
        </div>
        {/* end media area div */}
        {(data?.pages || 0) > 1 && (
          <Pagination
            current={page}
            totalPages={data?.pages}
            setPage={setPage}
          />
        )}
        {!standalone && (
          <div className="flex justify-end mt-[32px] gap-[8px]">
            <button
              onClick={() => modals.closeCurrent()}
              className="cursor-pointer h-[52px] px-[20px] items-center justify-center border border-newTextColor/10 flex rounded-[10px]"
            >
              {t('cancel', 'Cancel')}
            </button>
            {!isLoading && !!data?.results?.length && (
              <button
                onClick={standalone ? () => {} : addMedia}
                disabled={selected.length === 0}
                className="cursor-pointer text-white disabled:opacity-80 disabled:cursor-not-allowed h-[52px] px-[20px] items-center justify-center bg-[#612BD3] flex rounded-[10px]"
              >
                {t('add_selected_media', 'Add selected media')}
              </button>
            )}
          </div>
        )}
        </div>
        {/* end right column */}
      </div>
      {/* end root flex layout */}
    </DropFiles>
  );
};
export const MultiMediaComponent: FC<{
  label: string;
  description: string;
  mediaNotAvailable?: boolean;
  dummy: boolean;
  allData: {
    content: string;
    id?: string;
    image?: Array<{
      id: string;
      path: string;
    }>;
  }[];
  value?: Array<{
    path: string;
    id: string;
  }>;
  text: string;
  name: string;
  error?: any;
  onOpen?: () => void;
  onClose?: () => void;
  toolBar?: React.ReactNode;
  information?: React.ReactNode;
  onChange: (event: {
    target: {
      name: string;
      value?: Array<{
        id: string;
        path: string;
        alt?: string;
        thumbnail?: string;
        thumbnailTimestamp?: number;
      }>;
    };
  }) => void;
}> = (props) => {
  const {
    name,
    error,
    text,
    onChange,
    value,
    allData,
    dummy,
    toolBar,
    information,
    mediaNotAvailable,
  } = props;
  const user = useUser();
  const modals = useModals();
  const t = useT();
  const [currentMedia, setCurrentMedia] = useState(value);
  useEffect(() => {
    if (value !== undefined) {
      setCurrentMedia(value);
    }
  }, [value]);
  const mediaDirectory = useMediaDirectory();
  const changeMedia = useCallback(
    (
      m:
        | {
            path: string;
            id: string;
          }
        | {
            path: string;
            id: string;
          }[]
    ) => {
      const mediaArray = Array.isArray(m) ? m : [m];
      const newMedia = [...(currentMedia || []), ...mediaArray];
      setCurrentMedia(newMedia);
      onChange({
        target: {
          name,
          value: newMedia,
        },
      });
    },
    [currentMedia, onChange]
  );
  const showModal = useCallback(() => {
    modals.openModal({
      title: t('media_library', 'Media Library'),
      askClose: false,
      closeOnEscape: true,
      fullScreen: true,
      size: 'calc(100% - 80px)',
      height: 'calc(100% - 80px)',
      children: (close) => (
        <MediaBox setMedia={changeMedia} closeModal={close} />
      ),
    });
  }, [changeMedia, t]);

  const clearMedia = useCallback(
    (topIndex: number) => () => {
      const newMedia = currentMedia?.filter((f, index) => index !== topIndex);
      setCurrentMedia(newMedia);
      onChange({
        target: {
          name,
          value: newMedia,
        },
      });
    },
    [currentMedia, onChange]
  );

  const designMedia = useCallback(() => {
    if (!!user?.tier?.ai && !dummy) {
      modals.openModal({
        askClose: false,
        title: t('design_media', 'Design Media'),
        size: '80%',
        children: (close) => (
          <Polonto setMedia={changeMedia} closeModal={close} />
        ),
      });
    }
  }, [changeMedia, t]);

  return (
    <>
      <div className="b1 flex flex-col gap-[8px] rounded-bl-[8px] select-none w-full">
        <div className="flex gap-[10px] px-[12px]">
          {!!currentMedia && (
            <ReactSortable
              list={currentMedia}
              setList={(value) => {
                setCurrentMedia(value);
                onChange({ target: { name, value } });
              }}
              className="flex gap-[10px] sortable-container"
              animation={200}
              ghostClass="opacity-40"
              chosenClass="scale-105"
              handle=".dragging"
            >
              {currentMedia.map((media, index) => (
                  <div key={media.id} className="cursor-pointer rounded-[5px] w-[40px] h-[40px] border-2 border-tableBorder relative flex transition-all">
                    <DragHandleIcon className="z-[20] dragging absolute pe-[1px] pb-[3px] -start-[4px] -top-[4px] cursor-move" />

                    <div className="w-full h-full relative group">
                      <div
                        onClick={async () => {
                          modals.openModal({
                            title: t('media_settings', 'Media Settings'),
                            children: (close) => (
                              <MediaComponentInner
                                media={media as any}
                                onClose={close}
                                onSelect={(value: any) => {
                                  const updatedMedia = currentMedia.map((p) => {
                                    if (p.id === media.id) {
                                      return { ...p, ...value };
                                    }
                                    return p;
                                  });
                                  setCurrentMedia(updatedMedia);
                                  onChange({
                                    target: {
                                      name,
                                      value: updatedMedia,
                                    },
                                  });
                                }}
                              />
                            ),
                          });
                        }}
                        className="absolute top-[50%] left-[50%] -translate-x-[50%] -translate-y-[50%] bg-black/80 rounded-[10px] opacity-0 group-hover:opacity-100 transition-opacity z-[9]"
                      >
                        <MediaSettingsIcon className="cursor-pointer relative z-[200]" />
                      </div>
                      {hasExtension(media?.path, 'mp4') ? (
                        <VideoFrame url={mediaDirectory.set(media?.path)} />
                      ) : (
                        <img
                          className="w-full h-full object-cover rounded-[4px]"
                          src={mediaDirectory.set(media?.path)}
                        />
                      )}
                    </div>

                    <CloseCircleIcon
                      onClick={clearMedia(index)}
                      className="absolute -end-[4px] -top-[4px] z-[20] rounded-full bg-white"
                    />
                  </div>
              ))}
            </ReactSortable>
          )}
        </div>
        <div className="flex gap-[8px] px-[12px] border-t border-newColColor w-full b1 text-textColor">
          {!mediaNotAvailable && (
            <div className="flex py-[10px] b2 items-center gap-[4px]">
              <div
                onClick={showModal}
                className="cursor-pointer h-[30px] rounded-[6px] justify-center items-center flex bg-newColColor px-[8px]"
              >
                <div className="flex gap-[8px] items-center">
                  <div>
                    <InsertMediaIcon />
                  </div>
                  <div className="text-[10px] font-[600] maxMedia:hidden block">
                    {t('insert_media', 'Insert Media')}
                  </div>
                </div>
              </div>
              <div
                onClick={designMedia}
                className="cursor-pointer h-[30px] rounded-[6px] justify-center items-center flex bg-newColColor px-[8px]"
              >
                <div className="flex gap-[5px] items-center">
                  <div>
                    <DesignMediaIcon />
                  </div>
                  <div className="text-[10px] font-[600] iconBreak:hidden block">
                    {t('design_media', 'Design Media')}
                  </div>
                </div>
              </div>

              <ThirdPartyMedia allData={allData} onChange={changeMedia} />

              {!!user?.tier?.ai && (
                <>
                  <AiImage value={text} onChange={changeMedia} />
                  <AiVideo value={text} onChange={changeMedia} />
                </>
              )}
            </div>
          )}
          {!mediaNotAvailable && (
            <div className="text-newColColor h-full flex items-center">
              <VerticalDividerIcon />
            </div>
          )}
          {!!toolBar && (
            <div className="flex py-[10px] b2 items-center gap-[4px]">
              {toolBar}
            </div>
          )}
          {information && (
            <div className="flex-1 justify-end flex py-[10px] b2 items-center gap-[4px]">
              {information}
            </div>
          )}
        </div>
      </div>
      <div className="text-[12px] text-red-400">{error}</div>
    </>
  );
};
export const MediaComponent: FC<{
  label: string;
  description: string;
  value?: {
    path: string;
    id: string;
  };
  name: string;
  onChange: (event: {
    target: {
      name: string;
      value?: {
        id: string;
        path: string;
      };
    };
  }) => void;
  type?: 'image' | 'video';
  width?: number;
  height?: number;
}> = (props) => {
  const t = useT();

  const { name, type, label, description, onChange, value, width, height } =
    props;
  const { getValues } = useSettings();
  const user = useUser();
  useEffect(() => {
    const settings = getValues()[props.name];
    if (settings) {
      setCurrentMedia(settings);
    }
  }, []);
  const [currentMedia, setCurrentMedia] = useState(value);
  const modals = useModals();
  const mediaDirectory = useMediaDirectory();

  const showDesignModal = useCallback(() => {
    modals.openModal({
      title: t('media_editor', 'Media Editor'),
      askClose: false,
      closeOnEscape: true,
      fullScreen: true,
      size: 'calc(100% - 80px)',
      height: 'calc(100% - 80px)',
      children: (close) => (
        <Polonto
          width={width}
          height={height}
          setMedia={changeMedia}
          closeModal={close}
        />
      ),
    });
  }, [t]);
  const changeMedia = useCallback((m: { path: string; id: string }[]) => {
    setCurrentMedia(m[0]);
    onChange({
      target: {
        name,
        value: m[0],
      },
    });
  }, []);
  const showModal = useCallback(() => {
    modals.openModal({
      title: t('media_library', 'Media Library'),
      askClose: false,
      closeOnEscape: true,
      fullScreen: true,
      size: 'calc(100% - 80px)',
      height: 'calc(100% - 80px)',
      children: (close) => (
        <MediaBox setMedia={changeMedia} closeModal={close} type={type} />
      ),
    });
  }, [t]);
  const clearMedia = useCallback(() => {
    setCurrentMedia(undefined);
    onChange({
      target: {
        name,
        value: undefined,
      },
    });
  }, [value]);
  return (
    <div className="flex flex-col gap-[8px]">
      <div className="text-[14px]">{label}</div>
      <div className="text-[12px]">{description}</div>
      {!!currentMedia && (
        <div className="my-[20px] cursor-pointer w-[200px] h-[200px] border-2 border-tableBorder">
          <img
            className="w-full h-full object-cover"
            src={currentMedia.path}
            onClick={() => window.open(mediaDirectory.set(currentMedia.path))}
          />
        </div>
      )}
      <div className="flex gap-[5px]">
        <Button onClick={showModal}>{t('select', 'Select')}</Button>
        <Button onClick={showDesignModal} className="!bg-customColor45">
          {t('editor', 'Editor')}
        </Button>
        <Button secondary={true} onClick={clearMedia}>
          {t('clear', 'Clear')}
        </Button>
      </div>
    </div>
  );
};
