import { PrismaRepository } from '@gitroom/nestjs-libraries/database/prisma/prisma.service';
import { MediaRepository } from '@gitroom/nestjs-libraries/database/prisma/media/media.repository';

type Row = {
  id: string;
  organizationId: string;
  folder: string | null;
  deletedAt: Date | null;
};

/**
 * Prisma turns `startsWith` into a Postgres LIKE without escaping it, so `_`
 * matches any character and `%` any run of characters. The fake reproduces
 * that, because it is exactly what the repository must not trust.
 */
const likePrefix = (prefix: string) =>
  new RegExp(
    '^' +
      prefix
        .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        .replace(/_/g, '.')
        .replace(/%/g, '.*'),
    's'
  );

const fakePrisma = (rows: Row[]) => ({
  media: {
    findMany: jest.fn(async ({ where }) =>
      rows
        .filter(
          (r) =>
            r.organizationId === where.organizationId &&
            r.deletedAt === null &&
            r.folder !== null &&
            likePrefix(where.folder.startsWith).test(r.folder)
        )
        .map(({ id, folder }) => ({ id, folder }))
    ),
    updateMany: jest.fn(async ({ where, data }) => {
      const hit = rows.filter(
        (r) => where.id.in.includes(r.id) && r.folder === where.folder
      );
      hit.forEach((r) => (r.folder = data.folder));
      return { count: hit.length };
    }),
  },
  $transaction: jest.fn((operations: Promise<{ count: number }>[]) =>
    Promise.all(operations)
  ),
});

const setup = (folders: (string | null)[], extra: Row[] = []) => {
  const rows: Row[] = [
    ...folders.map((folder, i) => ({
      id: `m${i}`,
      organizationId: 'org',
      folder,
      deletedAt: null,
    })),
    ...extra,
  ];
  const prisma = fakePrisma(rows);
  const repository = new MediaRepository({
    model: prisma,
  } as unknown as PrismaRepository<'media'>);
  const folderOf = (id: string) => rows.find((r) => r.id === id)?.folder;
  const liveFolders = () =>
    rows
      .filter((r) => r.organizationId === 'org' && r.deletedAt === null)
      .map((r) => r.folder);
  return { repository, prisma, folderOf, liveFolders };
};

describe('MediaRepository.renameFolder', () => {
  it('treats "_" in the old name as a plain character', async () => {
    const { repository, liveFolders } = setup([
      'A_B',
      'A_B/sub',
      'A_B/sub/deep',
      'AxB',
      'AxB/sub',
      'A_B2',
    ]);

    const result = await repository.renameFolder('org', {
      oldName: 'A_B',
      newName: 'Z',
    });

    expect(liveFolders()).toEqual([
      'Z',
      'Z/sub',
      'Z/sub/deep',
      'AxB',
      'AxB/sub',
      'A_B2',
    ]);
    expect(result).toEqual({ count: 3 });
  });

  it('treats "%" in the old name as a plain character', async () => {
    const { repository, liveFolders } = setup(['A%', 'A%/x', 'Abc/x', 'A']);

    const result = await repository.renameFolder('org', {
      oldName: 'A%',
      newName: 'P',
    });

    expect(liveFolders()).toEqual(['P', 'P/x', 'Abc/x', 'A']);
    expect(result).toEqual({ count: 2 });
  });

  it('leaves deleted media and other organizations alone', async () => {
    const { repository, folderOf } = setup(
      ['Citem'],
      [
        { id: 'gone', organizationId: 'org', folder: 'Citem', deletedAt: new Date() },
        { id: 'other', organizationId: 'org2', folder: 'Citem', deletedAt: null },
      ]
    );

    await repository.renameFolder('org', { oldName: 'Citem', newName: 'NewBrand' });

    expect(folderOf('m0')).toBe('NewBrand');
    expect(folderOf('gone')).toBe('Citem');
    expect(folderOf('other')).toBe('Citem');
  });

  it('swaps only the prefix and renames each row once, in one transaction', async () => {
    const { repository, prisma, liveFolders } = setup(['A', 'A/B', 'A/A']);

    const result = await repository.renameFolder('org', {
      oldName: ' A ',
      newName: 'A/B',
    });

    expect(liveFolders()).toEqual(['A/B', 'A/B/B', 'A/B/A']);
    expect(result).toEqual({ count: 3 });
    expect(prisma.$transaction).toHaveBeenCalledTimes(1);
    expect(prisma.$transaction.mock.calls[0][0]).toHaveLength(3);
  });

  it('does nothing when both names are equal once trimmed', async () => {
    const { repository, prisma } = setup(['Citem']);

    const result = await repository.renameFolder('org', {
      oldName: 'Citem',
      newName: ' Citem ',
    });

    expect(result).toEqual({ count: 0 });
    expect(prisma.media.findMany).not.toHaveBeenCalled();
  });
});
