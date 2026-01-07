from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, ValidationError, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email
from flask_wtf.file import FileField, FileAllowed
from models.dynamodb_category import list_blog_categories_all, category_name_exists
from wtforms import StringField
from wtforms.validators import Optional, Length


class InquiryForm(FlaskForm):
    name = StringField('お名前', validators=[DataRequired()])
    email = StringField('メールアドレス', validators=[DataRequired(), Email()])
    title = StringField('タイトル', validators=[DataRequired()])
    text = TextAreaField('お問い合わせ内容', validators=[DataRequired()])
    submit = SubmitField('送信')


class BlogCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('保存')

    def validate_category(self, field):
        if category_name_exists(field.data):
            raise ValidationError('入力されたカテゴリ名は既に使われています。')


class UpdateCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('更新')

    def __init__(self, blog_category_id, *args, **kwargs):
        super(UpdateCategoryForm, self).__init__(*args, **kwargs)
        self.id = blog_category_id

    def validate_category(self, field):
        if category_name_exists(field.data, exclude_id=self.id):
            raise ValidationError('入力されたカテゴリ名は既に使われています。')


class BlogPostForm(FlaskForm):
    title = StringField('タイトル', validators=[DataRequired()])
    category = SelectField(
        'カテゴリ',
        coerce=int,
        validators=[],
        validate_choice=False
    )
    summary = StringField('要約')

    youtube_url = StringField(
        'YouTube URL（任意）',
        validators=[Optional(), Length(max=300)]
    )

    text = TextAreaField('本文', validators=[DataRequired()])
    picture = FileField(
        'アイキャッチ画像',
        validators=[
            FileAllowed(
                ['jpg', 'png', 'jpeg', 'gif', 'webp'],
                '画像ファイル（jpg, jpeg, png, gif, webp）を選択してください'
            )
        ]
    )
    video = FileField('動画', validators=[FileAllowed(['mp4', 'mov', 'avi'])])
    submit = SubmitField('投稿')

    def _set_category(self):
        try:
            blog_categories = list_blog_categories_all()
            if blog_categories:
                self.category.choices = [
                    (int(cat["category_id"]), cat["name"])
                    for cat in blog_categories
                ]
                if not self.category.data:
                    self.category.data = self.category.choices[0][0]
            else:
                self.category.choices = []
        except Exception as e:
            print(f"カテゴリー取得エラー: {e}")
            self.category.choices = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_category()


class BlogSearchForm(FlaskForm):
    searchtext = StringField('検索テキスト', validators=[DataRequired()])
    submit = SubmitField('検索')