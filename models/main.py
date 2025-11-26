from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, ValidationError, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email
from models.common import BlogCategory, BlogPost, Inquiry
from flask_wtf.file import FileField, FileAllowed


class BlogCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('保存')

    def validate_category(self, field):
        if BlogCategory.query.filter_by(name=field.data).first():
            raise ValidationError('入力されたカテゴリ名は既に使われています。')

class UpdateCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('更新')

    def __init__(self, blog_category_id, *args, **kwargs):
        super(UpdateCategoryForm, self).__init__(*args, **kwargs)
        self.id = blog_category_id

    def validate_category(self, field):
        exists = BlogCategory.query.filter_by(name=field.data).first()
        # 自分以外に同じ名前があればNG
        if exists and exists.id != self.id:
            raise ValidationError('入力されたカテゴリ名は既に使われています。')

class BlogPostForm(FlaskForm):
    title = StringField('タイトル', validators=[DataRequired()])
    # ★ DataRequired を外して、validate_choice=False を付ける
    category = SelectField(
        'カテゴリ',
        coerce=int,
        validators=[],
        validate_choice=False
    )
    summary = StringField('要約')
    text = TextAreaField('本文', validators=[DataRequired()])
    picture = FileField(
        'アイキャッチ画像',
        validators=[
            FileAllowed(
                ['jpg', 'png', 'jpeg', 'gif', 'webp'],  # ★ webp を追加
                '画像ファイル（jpg, jpeg, png, gif, webp）を選択してください'
            )
        ]
    )
    video = FileField('動画', validators=[FileAllowed(['mp4', 'mov', 'avi'])])  # 追加
    submit = SubmitField('投稿')

    def _set_category(self):
        try:
            blog_categories = BlogCategory.query.order_by(BlogCategory.id.asc()).all()
            if blog_categories:
                self.category.choices = [
                    (blog_category.id, blog_category.name)
                    for blog_category in blog_categories
                ]
                if not self.category.data:
                    self.category.data = self.category.choices[0][0]
            else:
                # ★ カテゴリが無い場合は単に空にする
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

class InquiryForm(FlaskForm):
    name = StringField('お名前（必須）', validators=[DataRequired()])
    email = StringField('メールアドレス（必須）', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    title = StringField('題名')
    text = TextAreaField('メッセージ本文（必須）', validators=[DataRequired()])
    submit = SubmitField('送信')