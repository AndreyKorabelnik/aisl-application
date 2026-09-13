package synthetic.fixture;

class BaseEntity {
    protected String id;
}

final class Customer extends BaseEntity {
    @Deprecated
    private String nickname;
    private Profile profile;
}

final class Profile {
    private String name;
}
