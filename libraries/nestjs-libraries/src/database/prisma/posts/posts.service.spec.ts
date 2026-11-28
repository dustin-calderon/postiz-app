import { NotFoundException } from '@nestjs/common';
import { PostsService } from '@gitroom/nestjs-libraries/database/prisma/posts/posts.service';

// The real manager loads every social provider, and some of them ship ESM that
// jest does not transform (same as refresh.integration.service.spec.ts).
jest.mock('@gitroom/nestjs-libraries/integrations/integration.manager', () => ({
  IntegrationManager: class {},
  socialIntegrationList: [],
}));
jest.mock('file-type', () => ({}), { virtual: true });
// Same for the sanitizer pulled in by the post DTOs, and for the injected
// services: they drag in the whole app (mail, billing, storage...) and
// ts-jest type-checks every file it loads.
jest.mock('isomorphic-dompurify', () => ({
  __esModule: true,
  default: { sanitize: (html: string) => html },
}));
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service',
  () => ({ IntegrationService: class {} })
);
jest.mock('@gitroom/nestjs-libraries/database/prisma/media/media.service', () => ({
  MediaService: class {},
}));
jest.mock('@gitroom/nestjs-libraries/short-linking/short.link.service', () => ({
  ShortLinkService: class {},
}));
jest.mock('@gitroom/nestjs-libraries/openai/openai.service', () => ({
  OpenaiService: class {},
}));
jest.mock(
  '@gitroom/nestjs-libraries/integrations/refresh.integration.service',
  () => ({ RefreshIntegrationService: class {} })
);
jest.mock('@gitroom/nestjs-libraries/upload/upload.factory', () => ({
  UploadFactory: class {},
}));
jest.mock('@gitroom/nestjs-libraries/redis/redis.service', () => ({
  ioRedis: {},
}));
jest.mock('@gitroom/nestjs-libraries/integrations/social.abstract', () => ({
  RefreshToken: class {},
}));
jest.mock('nestjs-temporal-core', () => ({ TemporalService: class {} }));

// getPost only talks to the repository and updateMedia; the rest of the
// constructor's dependencies are irrelevant here.
const setup = (found: unknown) => {
  const repositoryGetPost = jest.fn(async () => found);
  const service = Object.create(PostsService.prototype) as PostsService;
  (service as any)._postRepository = { getPost: repositoryGetPost };
  (service as any).updateMedia = jest.fn(async (_id: string, media: any) => media);
  return { service, repositoryGetPost };
};

describe('getPost', () => {
  it('answers 404 when the post does not exist for the organization', async () => {
    const { service, repositoryGetPost } = setup(null);

    await expect(service.getPost('org', 'missing')).rejects.toBeInstanceOf(
      NotFoundException
    );
    // looked up scoped to the organization, among the live posts
    expect(repositoryGetPost).toHaveBeenCalledWith('missing', true, 'org', true);
  });

  it('returns the group and the integration of a live post', async () => {
    const { service } = setup({
      id: 'p1',
      group: 'g1',
      integrationId: 'i1',
      integration: { picture: 'pic' },
      image: '[]',
      settings: '{}',
      childrenPost: [],
    });

    const post = await service.getPost('org', 'p1');

    expect(post.group).toBe('g1');
    expect(post.integration).toBe('i1');
    expect(post.integrationPicture).toBe('pic');
  });
});
